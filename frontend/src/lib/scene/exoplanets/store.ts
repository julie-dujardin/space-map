/**
 * The planetary systems the scene holds. The planet index loads once. A
 * system file loads when its system comes into view, or when one of its
 * stars or planets is the target of a navigation. Its planets go into the
 * body index; a host is looked up as a star, and its body places its planets.
 * A host with no place of its own, such as a resolved star system, takes the
 * place that the index gives it.
 */

import {
	extrasolarIdOf,
	extrasolarObjectId,
	planetObjectId,
	planetOfObjectId
} from '$lib/fetch/extrasolar/ids';
import {
	planetCatalogue,
	type PlanetCatalogue,
	type PlanetIndex,
	type PlanetIndexHost,
	type PlanetSystem
} from '$lib/fetch/extrasolar/planets';
import type { ExtrasolarLookupResult } from '$lib/fetch/extrasolar/lookup';
import type { Vec3 } from '$lib/scene/animation/math';
import { systemRoot } from '$lib/fetch/extrasolar/systems';
import { ensureExtrasolarBody } from '$lib/scene/setup/extrasolar';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { PositionedBody, StarAnchor } from '$lib/types/objects';
import {
	NO_ORBIT_AU,
	hostScene,
	makePlanetBodies,
	outerOrbitAU,
	outermostElements
} from './bodies';
import { framedPair, type DrawnPair } from './pair-orbits';
import { holdStarSystem, loadStarSystem, type StarSystemPlan } from './star-system';
import { orbitNormal, systemView, type SystemView } from './view';

/** System files held past the ones in use. */
const SYSTEMS_KEPT = 16;

export interface HeldSystem {
	file: PlanetSystem;
	/** Planet bodies by host ID. */
	planets: ReadonlyMap<number, readonly PositionedBody[]>;
}

export class ExoplanetStore {
	/** The planet index once it is in; null before, and where the host serves no planets. */
	index: PlanetIndex | null = null;
	/** By system key, least recently used first. */
	private readonly systems = new Map<number, HeldSystem>();
	private readonly loads = new Map<number, Promise<HeldSystem>>();
	/** The plans of star systems by root, least recently used first. */
	private readonly plans = new Map<number, StarSystemPlan>();
	private readonly planLoads = new Map<number, Promise<StarSystemPlan>>();
	/** Systems that are drawn or focused: never dropped. */
	private inUse: ReadonlySet<number> = new Set();

	constructor(
		private readonly ctx: ContextManager,
		private readonly catalogue: PlanetCatalogue = planetCatalogue
	) {}

	/** The catalogue keeps the index, and drops a load that failed. */
	loadIndex(): Promise<PlanetIndex | null> {
		return this.catalogue.index().then((index) => (this.index = index));
	}

	/** Hold the system of the star `hostId` and the star's body. Null when the
	 *  star has no planets. */
	async ensureHost(hostId: number): Promise<HeldSystem | null> {
		const entry = (await this.loadIndex())?.host(hostId);
		if (!entry) return null;
		const [held, found] = await Promise.all([
			this.ensureSystem(entry.system),
			ensureExtrasolarBody(this.ctx, extrasolarObjectId(hostId))
		]);
		this.placeHost(entry);
		await this.ensureStarSystemOf(found);
		return held;
	}

	/** Hold the star system of `root` and its bodies. */
	async ensureStarSystem(root: number): Promise<StarSystemPlan> {
		let load = this.planLoads.get(root);
		if (!load) {
			// The lookup holds the rows, so a second load reads no file.
			load = loadStarSystem(root)
				.then((plan) => holdStarSystem(this.ctx, plan))
				.then((plan) => this.holdPlan(plan))
				.finally(() => this.planLoads.delete(root));
			this.planLoads.set(root, load);
		}
		return load;
	}

	/** Hold the star system of a looked-up star. It brings the star's orbit
	 *  and light, and a link to a node frames its pair. A failed load leaves the
	 *  star on its own: the page still works. */
	async ensureStarSystemOf(found: ExtrasolarLookupResult): Promise<void> {
		const root = found.kind === 'live' ? systemRoot(found.record) : null;
		if (root === null) return;
		await this.ensureStarSystem(root).catch((e) => {
			console.warn(`[systems] the system ${root} did not load:`, e);
		});
	}

	private holdPlan(plan: StarSystemPlan): StarSystemPlan {
		this.plans.delete(plan.root);
		this.plans.set(plan.root, plan);
		for (const root of this.plans.keys()) {
			if (this.plans.size <= SYSTEMS_KEPT) break;
			this.plans.delete(root);
		}
		return plan;
	}

	/** Give a host body with no place the index's place. It gets no tree
	 *  place, so the starfield does not draw it as a star. */
	private placeHost(entry: PlanetIndexHost): void {
		const star = this.ctx.getBody(extrasolarObjectId(entry.id))?.extrasolar;
		if (star && !star.scene) star.scene = hostScene(entry);
	}

	/** Hold the system of the live planet a planet's scene ID leads to, maybe
	 *  through an alias. Nothing when it leads to none. An alias resolves to
	 *  the live body, so that a navigation to it finds its target. */
	async ensurePlanet(objectId: string): Promise<void> {
		const planet = planetOfObjectId(objectId);
		if (!planet) return;
		const live = (await this.loadIndex())?.live(planet.host, planet.n);
		if (!live) return;
		await this.ensureHost(live.host);
		const liveId = planetObjectId(live.host, live.n);
		if (liveId !== objectId) this.ctx.bodies.aliasExoplanet(objectId, liveId);
	}

	/** The held system of the star `hostId`, now. */
	held(hostId: number): HeldSystem | null {
		const entry = this.index?.host(hostId);
		return (entry && this.systems.get(entry.system)) || null;
	}

	/** Keep these systems while they are in use. */
	use(keys: ReadonlySet<number>): void {
		this.inUse = keys;
		for (const key of keys) {
			const held = this.systems.get(key);
			if (!held) continue;
			this.systems.delete(key);
			this.systems.set(key, held);
		}
		this.trim();
	}

	/** The camera place of a link to a host star, one of its planets, or a node
	 *  of a star system with a drawn orbit, once its system and its place are
	 *  in. The plane is the planet's own, else the plane of the node's pair, else
	 *  that of the star's outermost orbit. */
	view(objectId: string): SystemView | null {
		const frame = this.frameOf(objectId);
		return frame && systemView(frame.at, frame.normal, frame.outer || NO_ORBIT_AU);
	}

	/** The unit normal of the plane that {@link view} looks at. Null when it has no view. */
	planeNormal(objectId: string): Vec3 | null {
		return this.frameOf(objectId)?.normal ?? null;
	}

	private frameOf(objectId: string): { at: Readonly<Vec3>; normal: Vec3; outer: number } | null {
		const planet = planetOfObjectId(objectId);
		const hostId = planet?.host ?? extrasolarIdOf(objectId);
		if (hostId === null) return null;
		const held = this.held(hostId);
		const star = this.ctx.getBody(extrasolarObjectId(hostId))?.extrasolar;
		const pair = planet ? null : this.pairOf(star);
		const at = star?.scene;
		if ((!held && !pair) || !at) return null;
		const planets = held?.file.planets.filter((p) => p.host === hostId) ?? [];
		const own = planets.find((p) => p.number === planet?.n)?.elements;
		const plane = own ?? pair?.orbit ?? outermostElements(planets);
		const normal: Vec3 = plane ? orbitNormal(plane.i, plane.om) : [0, 1, 0];
		return { at, normal, outer: Math.max(pair?.orbit.a ?? 0, outerOrbitAU(planets) ?? 0) };
	}

	/** The pair that a page of the node `star` frames. Null for a star. */
	private pairOf(star: StarAnchor | undefined): DrawnPair | null {
		const root = star && systemRoot(star.record);
		const plan = root ? this.plans.get(root) : undefined;
		return plan ? framedPair(star!.id, plan.nodes, plan.pairs) : null;
	}

	private ensureSystem(key: number): Promise<HeldSystem> {
		const held = this.systems.get(key);
		if (held) return Promise.resolve(held);
		let load = this.loads.get(key);
		if (!load) {
			load = this.catalogue
				.system(key)
				.then((file) => this.hold(key, file))
				.finally(() => this.loads.delete(key));
			this.loads.set(key, load);
		}
		return load;
	}

	private hold(key: number, file: PlanetSystem): HeldSystem {
		const bodies = makePlanetBodies(file);
		this.ctx.bodies.addExoplanets(bodies);
		const planets = new Map<number, PositionedBody[]>();
		for (const body of bodies) {
			const host = body.exoplanet!.host;
			planets.set(host, [...(planets.get(host) ?? []), body]);
		}
		const held: HeldSystem = { file, planets };
		this.systems.set(key, held);
		this.trim();
		return held;
	}

	private trim(): void {
		for (const [key, held] of this.systems) {
			if (this.systems.size <= SYSTEMS_KEPT + this.inUse.size) break;
			if (this.inUse.has(key)) continue;
			this.systems.delete(key);
			for (const bodies of held.planets.values()) {
				this.ctx.bodies.dropExoplanets(bodies.map((b) => b.data.id));
			}
		}
	}
}
