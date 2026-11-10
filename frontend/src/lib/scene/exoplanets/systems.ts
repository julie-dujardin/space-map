/**
 * The planetary system the renderer draws, set once per frame: the system
 * of the focused star or planet. Each of its hosts draws by the pixel rule of
 * the solar system, with the halo, name and orbit line of each planet and of
 * each star on a drawn orbit. The centre of the focused star system has its halo
 * and name too. The starfield draws the host and the stars of the focused star
 * system at their exact places.
 */

import { ExtrasolarStaleError } from '$lib/fetch/extrasolar/files';
import { extrasolarIdOf, extrasolarObjectId } from '$lib/fetch/extrasolar/ids';
import { RetryBackoff } from '$lib/fetch/retry-backoff';
import type { Vec3 } from '$lib/scene/animation/math';
import type { PromotionRegistry } from '$lib/scene/focus/promotion';
import { HIDDEN_ROWS } from '$lib/scene/starfield/material';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import {
	isExoplanet,
	isExtrasolar,
	type PositionedBody,
	type StarAnchor
} from '$lib/types/objects';
import { SystemFades } from './fades';
import { FocusedStarSystem } from './star-system';

/** Stars the starfield draws at their exact place at once. A star past this
 *  stays a row. */
export const EXACT_STARS = HIDDEN_ROWS;
/** The key of the index among the loads, which no host ID is. */
const INDEX = 0;

export interface SystemsFrame {
	/** The date of the scene. */
	jd: number;
	/** Scene position of the camera, barycentre origin. */
	camera: Readonly<Vec3>;
	viewportPx: number;
	fovDeg: number;
	dtMs: number;
	/** 0 to 1: the share of the view outside the solar system. */
	outside: number;
	focused: PositionedBody | undefined;
}

export class ExoplanetSystems {
	private fades: SystemFades | null = null;
	/** Hosts whose system and body are on their way, and the index. */
	private readonly asked = new Set<number>();
	/** Failed loads wait before they are asked for again. */
	private readonly retries: RetryBackoff<number>;
	private readonly starSystem: FocusedStarSystem;
	/** Drawn hosts by camera distance, nearest first. */
	private drawn: number[] = [];
	/** The star whose light falls on the drawn planets; null while none draws
	 *  as a sphere. */
	lightStar: string | null = null;
	private drawnKey = '';

	constructor(
		private readonly ctx: ContextManager,
		private readonly promotion: PromotionRegistry,
		/** Called when a load lands that the next frame should draw. */
		private readonly onChange: () => void
	) {
		this.retries = new RetryBackoff(onChange);
		this.starSystem = new FocusedStarSystem(ctx, onChange);
	}

	/** True while a system fades in or out. */
	get fading(): boolean {
		return (this.fades?.fading ?? false) || this.starSystem.fading;
	}

	update(frame: SystemsFrame): void {
		this.starSystem.update(frame);
		const store = this.ctx.exoplanets;
		const star = this.starOf(frame.focused);
		if (!store.index) {
			if (star !== null) this.askIndex();
			this.drawn = [];
			this.publishDrawn(frame.focused);
			this.setShares(new Map());
			this.hold([]);
			this.syncBodies(frame.focused);
			return;
		}
		this.fades ??= new SystemFades(store.index);
		const key = star === null ? undefined : this.planetSystemOf(star);
		const hosts = key === undefined ? [] : store.index.hostsOf(key);
		for (const host of hosts) if (!this.loaded(host)) this.ask(host);
		const shares = this.fades.step({ ...frame, hosts, ready: (host) => this.ready(host) });

		const [cx, cy, cz] = frame.camera;
		const distance = (host: number): number => {
			const at = this.ctx.getBody(extrasolarObjectId(host))?.extrasolar?.scene;
			return at ? Math.hypot(at[0] - cx, at[1] - cy, at[2] - cz) : Infinity;
		};
		this.drawn = [...shares.keys()].sort((a, b) => distance(a) - distance(b));
		this.setShares(shares);
		this.publishDrawn(frame.focused);

		store.use(new Set(key === undefined ? [] : [key]));
		this.hold([...hosts, ...this.drawn]);
		this.syncBodies(frame.focused);
	}

	/** Publish the system that draws, for the credits, and the star that
	 *  lights it. Both hold while a system fades out. The light comes from the
	 *  host of a focused planet that draws, else from the nearest drawn host
	 *  with a planet drawn as a sphere. */
	private publishDrawn(focused: PositionedBody | undefined): void {
		const nearest = this.drawn[0];
		const key =
			nearest === undefined ? undefined : this.ctx.exoplanets.index?.host(nearest)?.system;
		this.ctx.visibility.planetSystemInView = key === undefined ? null : extrasolarObjectId(key);
		const focusedHost = focused?.exoplanet?.host;
		const lit =
			focusedHost !== undefined && focused?.data.mapped && this.drawn.includes(focusedHost)
				? focusedHost
				: this.drawn.find((host) =>
						this.ctx.exoplanets
							.held(host)
							?.planets.get(host)
							?.some((planet) => planet.data.mapped)
					);
		this.lightStar = lit === undefined ? null : extrasolarObjectId(lit);
	}

	/** The planetary system of a focused star: its own, that of the held host
	 *  that took over its point, or for a star on a drawn orbit that of its star
	 *  system. The root keys the file of a star system. */
	private planetSystemOf(star: number): number | undefined {
		const store = this.ctx.exoplanets;
		return store.index!.host(store.planetHostOf(star))?.system ?? this.starSystem.drawnRoot;
	}

	/** Publish the shares of the hosts, of the stars on drawn orbits and of the
	 *  system centres. */
	private setShares(hosts: ReadonlyMap<number, number>): void {
		const byId = new Map<string, number>();
		for (const [host, share] of hosts) byId.set(extrasolarObjectId(host), share);
		for (const [id, share] of this.starSystem.shares) {
			byId.set(id, Math.max(share, byId.get(id) ?? 0));
		}
		this.ctx.visibility.systemShares = byId;
		this.ctx.visibility.systemCentres = this.starSystem.centres;
	}

	/** Keep the bodies of `hosts` and of the focused star system. */
	private hold(hosts: readonly number[]): void {
		const ids = [...hosts, ...this.starSystem.ids];
		this.ctx.bodies.pinExtrasolar(new Set(ids.map(extrasolarObjectId)));
	}

	/** The stars to draw at their exact place, in this order: the star of the
	 *  focused body, the stars of the trip ends `endIds`, and the hosts of the
	 *  drawn systems, nearest first. A trip line ends on the stars of its ends.
	 *  The ends are looked up on each call, because an end can stream in late. */
	exactStars(focused: PositionedBody | undefined, endIds: readonly string[] = []): StarAnchor[] {
		const out: StarAnchor[] = [];
		const add = (anchor: StarAnchor | undefined) => {
			if (out.length === EXACT_STARS) return;
			const star = anchor?.drawnAt ? anchor : anchor && this.pointStar(anchor);
			const drawable = star?.tree || star?.drawnAt;
			if (star && drawable && !out.some((s) => s.id === star.id)) out.push(star);
		};
		const addStarOf = (body: PositionedBody | undefined) => {
			if (body && isExtrasolar(body)) add(body.extrasolar);
			if (body && isExoplanet(body)) add(this.ctx.getBody(body.data.parentId)?.extrasolar);
		};
		addStarOf(focused);
		for (const id of endIds) addStarOf(this.ctx.getBody(id));
		for (const host of this.drawn) add(this.ctx.getBody(extrasolarObjectId(host))?.extrasolar);
		return out;
	}

	/** The other stars of the focused star system, nearest first, in the slots
	 *  that `stars` leaves: a line or a planet needs its star exact more. */
	companions(stars: readonly StarAnchor[]): StarAnchor[] {
		const taken = new Set(stars.map((star) => star.id));
		return this.starSystem.stars
			.filter((star) => (star.tree || star.drawnAt) && !taken.has(star.id))
			.slice(0, EXACT_STARS - stars.length);
	}

	/** The star that draws the light of `anchor`. A node and a held star on no
	 *  drawn orbit have none of their own. A point that a held host took over
	 *  draws as the host, once the host has the point's row. */
	private pointStar(anchor: StarAnchor): StarAnchor | undefined {
		const held = this.ctx.exoplanets.heldHostOf(anchor.id);
		const host = held === undefined ? undefined : this.ctx.getBody(extrasolarObjectId(held));
		if (host?.extrasolar?.tree) return host.extrasolar;
		if (anchor.point === anchor.id) return anchor;
		const next = this.ctx.getBody(extrasolarObjectId(anchor.point))?.extrasolar;
		return next && this.pointStar(next);
	}

	/** The body whose halo stands for the object `id` of a focused star system. */
	haloBody(id: string): string {
		const star = extrasolarIdOf(id);
		return star === null ? id : extrasolarObjectId(this.starSystem.haloOf(star));
	}

	/** The star that a focused star or planet belongs to. */
	private starOf(body: PositionedBody | undefined): number | null {
		if (!body) return null;
		return body.exoplanet?.host ?? (isExtrasolar(body) ? (body.extrasolar?.id ?? null) : null);
	}

	private askIndex(): void {
		if (this.asked.has(INDEX) || this.retries.waiting(INDEX)) return;
		this.asked.add(INDEX);
		this.ctx.exoplanets.loadIndex().then(
			() => {
				this.retries.clear(INDEX);
				this.onChange();
			},
			(e) => {
				console.warn('[planets] the index did not load:', e);
				// Files from a newer export: the reload prompt is up, and nothing more loads.
				if (e instanceof ExtrasolarStaleError) return;
				this.asked.delete(INDEX);
				this.retries.fail(INDEX);
			}
		);
	}

	/** Hold a host's system and its body. */
	private ask(host: number): void {
		if (this.asked.has(host) || this.retries.waiting(host)) return;
		this.asked.add(host);
		this.ctx.exoplanets.ensureHost(host).then(
			() => {
				this.asked.delete(host);
				this.retries.clear(host);
				this.onChange();
			},
			(e) => {
				console.warn(`[planets] the system of ${host} did not load:`, e);
				if (e instanceof ExtrasolarStaleError) return;
				// Asked for again after a wait, if it is still wanted.
				this.asked.delete(host);
				this.retries.fail(host);
			}
		);
	}

	/** Whether a host's system and its body are held, and the body has the
	 *  place that the index gives a host with none of its own. */
	private loaded(host: number): boolean {
		const star = this.ctx.getBody(extrasolarObjectId(host))?.extrasolar;
		const placed = !!star?.scene || !this.ctx.exoplanets.index?.host(host)?.position;
		return this.ctx.exoplanets.held(host) !== null && !!star && placed;
	}

	/** A host shows once its planets are in and it has a place. */
	private ready(host: number): boolean {
		const star = this.ctx.getBody(extrasolarObjectId(host));
		return this.ctx.exoplanets.held(host) !== null && !!star?.extrasolar?.scene;
	}

	/** Give the drawn planets, their hosts, the stars on drawn orbits and the
	 *  system centres a halo and a name, and take them from the ones that left. */
	private syncBodies(focused: PositionedBody | undefined): void {
		const bodies: PositionedBody[] = [];
		for (const host of this.drawn) {
			const star = this.ctx.getBody(extrasolarObjectId(host));
			if (star) bodies.push(star);
			bodies.push(...(this.ctx.exoplanets.held(host)?.planets.get(host) ?? []));
		}
		const shown = new Set(this.starSystem.shares.keys());
		for (const [id, share] of this.starSystem.centres) if (share > 0) shown.add(id);
		for (const id of shown) {
			const star = this.ctx.getBody(id);
			if (star) bodies.push(star);
		}
		const key = `${bodies.map((b) => b.data.id).join(',')}|${focused?.data.id ?? ''}`;
		if (key === this.drawnKey) return;
		this.drawnKey = key;
		this.promotion.syncSystemBodies(bodies);
	}
}
