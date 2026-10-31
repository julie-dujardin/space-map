/**
 * The star system of the focused body. Every point of the system draws as an
 * exact star while the focus is in the system, because the float32 place of a
 * row moves in steps when the camera is near it.
 *
 * Each drawn pair of the system puts its two members on its orbit about the
 * pair's body, as a planet orbits its star. The star bodies keep their IDs, so
 * focus, labels, trails and picks take them by the paths of the planets. A
 * star takes its orbit once the focus is in its system, and leaves it once the
 * focus has left and the orbit has faded out.
 *
 * The body of the root is the centre of the system, as the Sun is the centre of
 * the solar system. It carries the halo and name of the system while the focus
 * is in the system, with no threshold of its own. A star on the barycentre of
 * the pair that a node frames takes over the node: the star carries the halo,
 * and the node draws none, also on its own page.
 */

import { ExtrasolarStaleError } from '$lib/fetch/extrasolar/files';
import { extrasolarObjectId } from '$lib/fetch/extrasolar/ids';
import { homeRow } from '$lib/fetch/extrasolar/lookup';
import {
	loadSystemNodes,
	systemPointIds,
	systemRoot,
	type SystemNode
} from '$lib/fetch/extrasolar/systems';
import { RetryBackoff } from '$lib/fetch/retry-backoff';
import { AU_SCALE, SOLAR_RADIUS_KM } from '$lib/math/units';
import type { Vec3 } from '$lib/scene/animation/math';
import { putOnOrbit, takeOffOrbit } from '$lib/scene/position/placement';
import { ensureExtrasolarBody } from '$lib/scene/setup/extrasolar';
import { bpRpFromTeff, starCssColour } from '$lib/scene/starfield/colour';
import { colourBv, gEstimate } from '$lib/scene/starfield/record';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { SwitchFade } from '$lib/scene/visibility/switch-fade';
import { pxPerRad, systemShown } from '$lib/scene/visibility/system-fade';
import type { PositionedBody, StarAnchor } from '$lib/types/objects';
import {
	barycentreOf,
	drawnPairs,
	framedPair,
	haloCarrier,
	pairElements,
	pairLight,
	splitLight,
	starsShare,
	type DrawnPair
} from './pair-orbits';
import type { SystemsFrame } from './systems';

/** Two bodies nearer than this (scene units) sit at one spot. */
const SAME_PLACE_SCENE = 1e-6;

/** What a star system draws up close, from its System rows. */
export interface StarSystemPlan {
	root: number;
	nodes: ReadonlyMap<number, SystemNode>;
	/** The IDs with a point of their own. */
	points: readonly number[];
	/** The pairs that draw, outermost first. */
	pairs: readonly DrawnPair[];
	/** Every ID that needs a body: the root, the points and the drawn pairs and
	 *  members. */
	ids: readonly number[];
}

/** One drawn pair in the scene. */
interface PairState {
	pair: DrawnPair;
	/** Its orbit is wide enough on screen to show. */
	shown: boolean;
	fade: SwitchFade;
	/** The share of the light of its point that its two stars draw. */
	handed: number;
}

/** A system whose stars are on their orbits. */
interface DrawnSystem {
	plan: StarSystemPlan;
	pairs: PairState[];
	/** The members with light of their own. A resolved node has none. */
	stars: number[];
}

/** The rows of the system of `root` and the pairs in them. */
export async function loadStarSystem(root: number): Promise<StarSystemPlan> {
	const rows = await loadSystemNodes(root);
	const nodes = new Map(rows.map((node) => [node.id, node]));
	const points = systemPointIds(rows[0]?.tree ?? [], rows);
	const pairs = drawnPairs(nodes);
	const members = pairs.flatMap(({ node, first, second }) => [node.id, first, second]);
	return { root, nodes, points, pairs, ids: [...new Set([root, ...points, ...members])] };
}

/** The points of a system on no drawn orbit, but for the one on its centre
 *  and those whose own stars draw. */
function wideStars({ root, nodes, pairs, points }: StarSystemPlan): number[] {
	const taken = new Set(pairs.flatMap(({ node, first, second }) => [node.id, first, second]));
	taken.add(haloCarrier(root, nodes, pairs));
	return points.filter((id) => !taken.has(id));
}

/** A resolved node has no point, so its stars draw and it does not. */
function isResolved(plan: StarSystemPlan, id: number): boolean {
	const node = plan.nodes.get(id);
	return node !== undefined && node.members.length > 0 && !node.point;
}

function samePlace(a: Readonly<Vec3>, b: Readonly<Vec3>): boolean {
	return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]) < SAME_PLACE_SCENE;
}

/**
 * Hold the bodies of a plan, and give them what a page and a drawn star need
 * from the System rows. A drawn pair with a member that has no body or no place
 * leaves the plan. Each call gives the values again, because a body that left
 * the LRU comes back with the values of its record.
 */
export async function holdStarSystem(
	ctx: ContextManager,
	plan: StarSystemPlan
): Promise<StarSystemPlan> {
	await Promise.all(plan.ids.map((id) => ensureExtrasolarBody(ctx, extrasolarObjectId(id))));
	const anchor = (id: number) => ctx.getBody(extrasolarObjectId(id))?.extrasolar;
	/** The catalogue keeps a resolved pair's barycentre where its stars are. */
	const placeOf = (id: number): Vec3 | null => {
		const pair = plan.pairs.find((p) => p.node.id === id);
		if (!pair || pair.node.point) return anchor(id)?.scene ?? null;
		const first = placeOf(pair.first);
		const second = placeOf(pair.second);
		return first && second && barycentreOf(first, second, pair.orbit.barycentre);
	};
	const pairs = plan.pairs.filter(
		({ node, first, second }) =>
			placeOf(node.id) !== null && anchor(first) !== undefined && anchor(second) !== undefined
	);
	const insidePoints = new Map<number, number | null>();
	for (const pair of pairs) {
		const star = anchor(pair.node.id);
		if (star && !pair.node.point) star.scene = placeOf(pair.node.id);
		describeMembers(ctx, plan, pair, insidePoints);
	}
	// A node with no drawn orbit of its own sits at the pair it frames.
	for (const id of plan.nodes.keys()) {
		const framed = pairs.some((p) => p.node.id === id) ? null : framedPair(id, plan.nodes, pairs);
		const star = anchor(id);
		const at = framed && anchor(framed.node.id)?.scene;
		if (star && at) star.scene = at;
	}
	return pairs.length === plan.pairs.length ? plan : { ...plan, pairs };
}

/** An apparent magnitude as absolute G at the distance of the node. */
function absoluteAt(node: SystemNode, apparent: number | null): number | null {
	if (apparent === null || node.distance === null) return null;
	return apparent - 5 * Math.log10(node.distance) + 5;
}

/** The light, colour and size of the two members of a pair. `insidePoints`
 *  holds the absolute G of each node inside a point, which its stars split. */
function describeMembers(
	ctx: ContextManager,
	plan: StarSystemPlan,
	pair: DrawnPair,
	insidePoints: Map<number, number | null>
): void {
	const { node } = pair;
	const body = (id: number) => ctx.getBody(extrasolarObjectId(id));
	const primary = body(node.primary!)?.extrasolar;
	const members = node.members;
	const values = members.map((m) => plan.nodes.get(m.id!)?.star ?? null);
	const home = primary && homeRow(primary.record);
	const inPoint = node.point || insidePoints.has(node.id);
	const bv = inPoint && home ? colourBv(home) : null;
	const magnitudes = members.map((m) => {
		const v = inPoint ? gEstimate(m.vMag, bv, null) : m.vMag;
		return absoluteAt(node, m.gMag ?? v);
	});
	const total = node.point ? (primary?.absMag ?? null) : (insidePoints.get(node.id) ?? null);
	const light = inPoint
		? splitLight(
				total,
				[magnitudes[0], magnitudes[1]],
				[values[0]?.mass ?? members[0].mass, values[1]?.mass ?? members[1].mass]
			)
		: magnitudes;
	members.forEach((member, i) => {
		if (inPoint && member.kind === 'system') insidePoints.set(member.id!, light[i]);
		const star = body(member.id!);
		const anchor = star?.extrasolar;
		if (!star || !anchor) return;
		const held = values[i];
		if (held) {
			anchor.absMag = light[i];
			anchor.teff = held.teff;
			anchor.colour = held.teff === null ? (primary?.colour ?? null) : bpRpFromTeff(held.teff);
			anchor.radiusKm = held.radius === null ? null : held.radius * SOLAR_RADIUS_KM;
			star.data.radiusKm = anchor.radiusKm ?? NaN;
		}
		const inner = plan.nodes.get(member.id!)?.primary;
		const look = inner ? body(inner)?.extrasolar : anchor;
		star.data.starColor = starCssColour(look?.teff ?? null, look?.colour ?? null);
	});
}

export class FocusedStarSystem {
	private root: number | null = null;
	/** The plan of `root`, once its rows and bodies are in. */
	private plan: StarSystemPlan | null = null;
	/** The stars of `plan` on no drawn orbit and off its centre. */
	private wide: readonly number[] = [];
	/** The focused system and the ones that fade out, by root. */
	private readonly drawn = new Map<number, DrawnSystem>();
	private near: StarAnchor[] = [];
	private centreShares: ReadonlyMap<string, number> = new Map();
	private asked = false;
	/** Failed loads wait before they are asked for again. */
	private readonly retries: RetryBackoff<number>;

	constructor(
		private readonly ctx: ContextManager,
		/** Called when a load lands that the next frame should draw. */
		private readonly onChange: () => void
	) {
		this.retries = new RetryBackoff(onChange);
	}

	/** The IDs of the bodies to hold. */
	get ids(): readonly number[] {
		const plans = [this.plan, ...[...this.drawn.values()].map((system) => system.plan)];
		return [...new Set(plans.flatMap((plan) => plan?.ids ?? []))];
	}

	/** The stars whose records are in, nearest the camera first. */
	get stars(): readonly StarAnchor[] {
		return this.near;
	}

	/** The root of the focused system while its stars are on their orbits. */
	get drawnRoot(): number | undefined {
		return this.root !== null && this.drawn.has(this.root) ? this.root : undefined;
	}

	/** True while a drawn orbit fades in or out. */
	get fading(): boolean {
		for (const { pairs } of this.drawn.values()) {
			if (pairs.some(({ fade }) => fade.fading)) return true;
		}
		return false;
	}

	/** The share of each body on a drawn orbit that shows its halo, name and
	 *  line, by object ID, and 1 for a star on no orbit. A body with no share
	 *  is not in the map. */
	get shares(): ReadonlyMap<string, number> {
		const shares = new Map<string, number>();
		for (const id of this.wide) shares.set(extrasolarObjectId(id), 1);
		for (const { pairs } of this.drawn.values()) {
			for (const { pair, fade } of pairs) {
				if (fade.share === 0) continue;
				shares.set(extrasolarObjectId(pair.first), fade.share);
				shares.set(extrasolarObjectId(pair.second), fade.share);
			}
		}
		return shares;
	}

	/** The share of the centre of each system in view that shows, by object ID:
	 *  1, or 0 while the focused body sits on it and its ring stands for both.
	 *  A node that a star takes over has 0, and its star 1. */
	/** The ID whose halo stands for `id`: the star that takes over a node, or
	 *  the root at the node's place, which shows one halo for both. */
	haloOf(id: number): number {
		if (!this.plan) return id;
		const { root, nodes, pairs } = this.plan;
		const own = haloCarrier(id, nodes, pairs);
		const centre = haloCarrier(root, nodes, pairs);
		const [at, centreAt] = [this.star(own)?.scene, this.star(centre)?.scene];
		return at && centreAt && samePlace(at, centreAt) ? centre : own;
	}

	get centres(): ReadonlyMap<string, number> {
		return this.centreShares;
	}

	/** Follow the focus. Call this after the bodies moved for the frame. */
	update(frame: SystemsFrame): void {
		const root = this.rootOf(frame.focused);
		if (root !== this.root) {
			this.root = root;
			this.plan = null;
			this.setWide([]);
			// A body that went past the LRU loads again on the way back.
			this.asked = false;
		}
		if (root !== null) this.ask(root);
		const plan = this.plan;
		if (plan && plan.pairs.length > 0 && !this.drawn.has(plan.root)) this.draw(plan);
		if (plan && this.wide.length === 0) this.setWide(wideStars(plan));
		for (const system of this.drawn.values()) this.step(system, frame);
		this.near = this.nearStars(frame.camera);
		this.centreShares = this.findCentres(frame);
	}

	/** A centre leaves with the last orbit of its system. */
	private findCentres({ focused, jd }: SystemsFrame): ReadonlyMap<string, number> {
		const plans = [...this.drawn.values()].map(({ plan }) => plan);
		if (this.plan && !this.drawn.has(this.plan.root)) plans.push(this.plan);
		const focusId = focused?.extrasolar?.id;
		const centres = new Map<string, number>();
		for (const { root, nodes, pairs } of plans) {
			const carrier = (id: number) => haloCarrier(id, nodes, pairs);
			const centre = this.body(carrier(root));
			const at = centre ? this.ctx.place(centre, jd) : null;
			if (!centre || !at) continue;
			const shown = focusId === undefined ? focused : this.body(carrier(focusId));
			const focus = shown && shown !== centre ? this.ctx.place(shown, jd) : null;
			centres.set(centre.data.id, focus && samePlace(focus, at) ? 0 : 1);
			// A node that a star takes over draws no halo, also as the focus.
			for (const id of focusId === undefined ? [root] : [root, focusId]) {
				if (carrier(id) === id) continue;
				centres.set(extrasolarObjectId(id), 0);
				centres.set(extrasolarObjectId(carrier(id)), 1);
			}
		}
		return centres;
	}

	/** The stars to draw at their exact place, nearest first. */
	private nearStars([cx, cy, cz]: Readonly<Vec3>): StarAnchor[] {
		const ids = new Set(this.plan?.points);
		// A point draws its share of the light until its orbit has faded out.
		for (const { plan, stars } of this.drawn.values()) {
			for (const id of [...plan.points, ...stars]) ids.add(id);
		}
		const distance = ({ drawnAt, scene }: StarAnchor): number => {
			const at = drawnAt ?? scene;
			return at ? Math.hypot(at[0] - cx, at[1] - cy, at[2] - cz) : Infinity;
		};
		return [...ids].flatMap((id) => this.star(id) ?? []).sort((a, b) => distance(a) - distance(b));
	}

	private body(id: number): PositionedBody | undefined {
		return this.ctx.getBody(extrasolarObjectId(id));
	}

	private star(id: number): StarAnchor | undefined {
		return this.body(id)?.extrasolar;
	}

	/** A star on no orbit takes its tiers by its distance from the centre. */
	private setWide(ids: readonly number[]): void {
		for (const id of this.wide) {
			const star = this.star(id);
			if (star) star.pairAxis = undefined;
		}
		const centre =
			this.plan && this.star(haloCarrier(this.plan.root, this.plan.nodes, this.plan.pairs));
		this.wide = ids.filter((id) => {
			const [star, from] = [this.star(id), centre?.scene];
			if (!star?.scene || !from) return false;
			star.pairAxis = Math.hypot(...star.scene.map((v, k) => v - from[k])) / AU_SCALE;
			return true;
		});
	}

	private draw(plan: StarSystemPlan): void {
		for (const { node, orbit, first, second } of plan.pairs) {
			const parentId = extrasolarObjectId(node.id);
			const [ofFirst, ofSecond] = pairElements(orbit);
			const onOrbit = [
				[this.body(first), ofFirst],
				[this.body(second), ofSecond]
			] as const;
			for (const [body, elements] of onOrbit) {
				if (!body?.extrasolar) continue;
				putOnOrbit(body, parentId, elements);
				body.extrasolar.pairAxis = orbit.a;
			}
		}
		const members = plan.pairs.flatMap(({ first, second }) => [first, second]);
		this.drawn.set(plan.root, {
			plan,
			pairs: plan.pairs.map((pair) => ({
				pair,
				shown: false,
				fade: new SwitchFade(false),
				handed: 0
			})),
			stars: members.filter((id) => !isResolved(plan, id))
		});
		// The next pass places them, also on a paused clock.
		this.ctx.bodies.notifyBodiesAdded();
	}

	private undraw({ plan, pairs, stars }: DrawnSystem): void {
		this.drawn.delete(plan.root);
		for (const { pair } of pairs) {
			for (const id of [pair.first, pair.second]) {
				const body = this.body(id);
				if (body) takeOffOrbit(body);
				if (body?.extrasolar) body.extrasolar.pairAxis = undefined;
			}
			const point = this.star(pair.node.id);
			if (point) point.light = undefined;
		}
		for (const id of stars) {
			const star = this.star(id);
			if (star) {
				star.drawnAt = undefined;
				star.light = undefined;
			}
		}
		this.ctx.bodies.notifyBodiesAdded();
	}

	/** Move the stars of a system and hand its light over for this frame. */
	private step(system: DrawnSystem, frame: SystemsFrame): void {
		const { camera, jd, dtMs, viewportPx, fovDeg, outside } = frame;
		const wanted = system.plan.root === this.root;
		const placeOf = (id: number): Readonly<Vec3> | null => {
			const body = this.body(id);
			return body ? this.ctx.place(body, jd) : null;
		};
		for (const id of system.stars) {
			const star = this.star(id);
			if (star) star.drawnAt = placeOf(id) ?? undefined;
		}
		let done = !wanted;
		for (const state of system.pairs) {
			const { node, orbit, first, second } = state.pair;
			const at = placeOf(node.id);
			const distance = at
				? Math.hypot(at[0] - camera[0], at[1] - camera[1], at[2] - camera[2])
				: Infinity;
			state.shown = systemShown(distance, viewportPx, fovDeg, state.shown, orbit.a);
			state.fade.step(wanted && state.shown && outside > 0, dtMs);
			if (state.fade.share > 0) done = false;
			const a = placeOf(first);
			const b = placeOf(second);
			const apart = a && b ? Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]) : 0;
			const stars = starsShare((apart / distance) * pxPerRad(viewportPx, fovDeg));
			state.handed = stars * state.fade.share;
		}
		for (const [id, light] of pairLight(system.pairs)) {
			const star = this.star(id);
			if (star) star.light = light;
		}
		if (done) this.undraw(system);
	}

	/** The system of a focused star, node, held star or planet. */
	private rootOf(body: PositionedBody | undefined): number | null {
		const host = body?.exoplanet?.host;
		const star = host === undefined ? body : this.ctx.getBody(extrasolarObjectId(host));
		const record = star?.extrasolar?.record;
		return record ? systemRoot(record) : null;
	}

	private ask(root: number): void {
		if (this.asked || this.retries.waiting(root)) return;
		this.asked = true;
		this.ctx.exoplanets.ensureStarSystem(root).then(
			(plan) => {
				this.retries.clear(root);
				if (root !== this.root) return;
				this.plan = plan;
				this.onChange();
			},
			(e) => {
				console.warn(`[systems] the system ${root} did not load:`, e);
				// Files from a newer export: the reload prompt is up, and nothing more loads.
				if (e instanceof ExtrasolarStaleError) return;
				if (root === this.root) this.asked = false;
				this.retries.fail(root);
			}
		);
	}
}
