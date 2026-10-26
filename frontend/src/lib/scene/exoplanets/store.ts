/**
 * The planetary systems the scene holds. The planet index loads once. A
 * system file loads when its system comes into view, or when one of its
 * stars or planets is the target of a navigation. Its planets go into the
 * body index; a host is looked up as a star, and its body places its planets.
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
	type PlanetSystem
} from '$lib/fetch/extrasolar/planets';
import { ensureExtrasolarBody } from '$lib/scene/setup/extrasolar';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { PositionedBody } from '$lib/types/objects';
import { NO_ORBIT_AU, makePlanetBodies, outerOrbitAU, outermostElements } from './bodies';
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
		const [held] = await Promise.all([
			this.ensureSystem(entry.system),
			ensureExtrasolarBody(this.ctx, extrasolarObjectId(hostId))
		]);
		return held;
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

	/** The camera place of a link to a host star or one of its planets, once
	 *  its system and the star's place are in. The plane is the planet's own,
	 *  or for a star the plane of its outermost orbit. */
	view(objectId: string): SystemView | null {
		const planet = planetOfObjectId(objectId);
		const hostId = planet?.host ?? extrasolarIdOf(objectId);
		if (hostId === null) return null;
		const held = this.held(hostId);
		const at = this.ctx.getBody(extrasolarObjectId(hostId))?.extrasolar?.scene;
		if (!held || !at) return null;
		const planets = held.file.planets.filter((p) => p.host === hostId);
		const own = planets.find((p) => p.number === planet?.n)?.elements;
		const plane = own ?? outermostElements(planets);
		const normal = plane ? orbitNormal(plane.i, plane.om) : ([0, 1, 0] as const);
		return systemView(at, normal, outerOrbitAU(planets) ?? NO_ORBIT_AU);
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
