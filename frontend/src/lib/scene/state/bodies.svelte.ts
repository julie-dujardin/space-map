import { ObjectType, isAsteroid, type PositionedBody } from '$lib/types/objects';
import type { MinorBucket } from '$lib/fetch/position/minor-columns';
import { EARTH_ID, SSB_ID, SUN_ID } from '$lib/constants';

/** True if parentId is a top-level parent (SSB or Sun), not a planetary system. */
export function isTopLevelParent(parentId: string): boolean {
	return parentId === SSB_ID || parentId === SUN_ID;
}

/** Barycenter → dominant planet id (`naif-{X}` → `naif-{X}99`, SPICE convention),
 *  or null if `id` isn't a barycenter. Barycenters carry no name/frame of their own. */
export function dominantPlanetId(id: string): string | null {
	const m = /^naif-([1-9])$/.exec(id);
	return m ? `naif-${m[1]}99` : null;
}

/** The physical body a focused object could clip into: its direct parent,
 *  resolved to dominant planet. Undefined for Sun/SSB orbiters — too far to reach. */
export function collisionParentId(parentId: string): string | undefined {
	if (isTopLevelParent(parentId)) return undefined;
	return dominantPlanetId(parentId) ?? parentId;
}

/** The scene's body store: every loaded `PositionedBody` plus the parent/child
 *  graph. Loaders write through it; visibility and per-frame loops read from it. */
export class BodyIndex {
	/** All major-tier bodies, keyed by object id. */
	readonly bodiesById = new Map<string, PositionedBody>();

	/** Promoted-for-render subset of `bodiesById`, excluding barycenters,
	 *  Lagrange points, and SPICE probes — keeps the renderer's hot loops small. */
	majorBodies: PositionedBody[] = [];

	/** Per-zone asteroid buckets. Each {@link MinorBucket} materializes a
	 *  `PositionedBody` on demand so ~1.3M dots render off the worker SoA
	 *  without allocating objects. `small_body_moons` ride here too. */
	asteroidBodiesByZone = new Map<string, MinorBucket>();

	/** Per-parent spacecraft buckets. Earth sats/debris stay on this AoS path
	 *  (small count, plus ZoneRefresher's hot-reload/group-filter machinery)
	 *  rather than a {@link MinorBucket}. */
	spacecraftByParent = new Map<string, Map<string, PositionedBody>>();

	/** The one synthetic surface-feature body currently focused, if any. Kept off
	 *  `bodiesById`/`majorBodies` — the renderer re-seats it each frame — but
	 *  resolvable via {@link getBody}. */
	focusFeature: PositionedBody | null = null;

	/** Zones/groups that received new data since last rebuild. Cleared by the consumer. */
	dirtyAsteroidZones = new Set<string>();
	dirtySpacecraftGroups = new Set<string>();

	/** True while the phase-2 minor-chunk stream is in flight, throttling
	 *  point-cloud full-zone repacks ({@link PointCloudSystem.rebuildMinor}). */
	minorStreaming = false;

	/** Incremented on each minor-body data flush; read by Scene.svelte to trigger point cloud rebuilds. */
	minorBodyVersion = $state(0);

	/** Bumped when `loadSystemData` attaches `orientation` to a body, so reactive
	 *  consumers (compass-north list) re-derive — a `$state.raw` mutation
	 *  wouldn't otherwise retrigger. */
	orientationVersion = $state(0);

	/** Parent → children index (object ids only), for O(1) system-membership checks. */
	private readonly childrenByParent = new Map<string, Set<string>>();

	/** Max semi-major axis (AU) of moons per parent body id. Used to size the
	 *  shadow camera frustum and to gate point-cloud visibility. */
	private readonly moonMaxAByParent = new Map<string, number>();

	/** Subscribers notified after any bucket gains new ids — drives promotion
	 *  matching without per-frame zone scans. */
	private readonly addListeners = new Set<(ids: readonly string[]) => void>();

	/** Subscribe to bulk additions across any bucket. Fires with freshly-added
	 *  ids only; updates to existing entries aren't announced. */
	onBodiesAdded(cb: (ids: readonly string[]) => void): () => void {
		this.addListeners.add(cb);
		return () => this.addListeners.delete(cb);
	}

	/** Fire `onBodiesAdded` listeners; also called directly by loaders that
	 *  mutate zone buckets outside `addBodies`. */
	notifyBodiesAdded(ids: readonly string[]): void {
		if (ids.length === 0 || this.addListeners.size === 0) return;
		for (const cb of this.addListeners) cb(ids);
	}

	/** Look up any body by ID. Pass `zone` to skip the linear bucket scan when
	 *  it's already known. */
	getBody(id: string, zone?: string): PositionedBody | undefined {
		const major = this.bodiesById.get(id);
		if (major) return major;
		if (this.focusFeature?.data.id === id) return this.focusFeature;
		if (zone !== undefined) {
			return (
				this.spacecraftByParent.get(zone)?.get(id) ?? this.asteroidBodiesByZone.get(zone)?.get(id)
			);
		}
		for (const byId of this.spacecraftByParent.values()) {
			const hit = byId.get(id);
			if (hit) return hit;
		}
		for (const byId of this.asteroidBodiesByZone.values()) {
			const hit = byId.get(id);
			if (hit) return hit;
		}
		return undefined;
	}

	/** Register a batch of bodies: updates `bodiesById`, the parent/child index,
	 *  and the moon-max-a tracker. Orbit-source attribution is the caller's job
	 *  (see CreditsStore.recordOrbitSources). */
	addBodies(bodies: PositionedBody[]): void {
		const addedIds: string[] = [];
		for (const b of bodies) {
			if (!this.bodiesById.has(b.data.id)) addedIds.push(b.data.id);
			this.bodiesById.set(b.data.id, b);

			const set = this.childrenByParent.get(b.data.parentId) ?? new Set<string>();
			set.add(b.data.id);
			this.childrenByParent.set(b.data.parentId, set);
			if (b.data.objectType === ObjectType.MOON) {
				const prev = this.moonMaxAByParent.get(b.data.parentId) ?? 0;
				if (b.data.a > prev) this.moonMaxAByParent.set(b.data.parentId, b.data.a);
			}
		}
		this.notifyBodiesAdded(addedIds);
	}

	/** Children of `parentId` (object ids), or undefined if none registered. */
	getChildren(parentId: string): Set<string> | undefined {
		return this.childrenByParent.get(parentId);
	}

	/** Zone holding an asteroid/comet body, or undefined for non-belt bodies.
	 *  Linear scan — fine at promoted-body cardinality. */
	findAsteroidZone(id: string): string | undefined {
		for (const [zone, byId] of this.asteroidBodiesByZone) {
			if (byId.has(id)) return zone;
		}
		return undefined;
	}

	/** Max moon-orbit semi-major axis (AU) under `parentId`, or undefined. */
	maxMoonA(parentId: string): number | undefined {
		return this.moonMaxAByParent.get(parentId);
	}

	/** Max moon semi-major axis (AU) in a system, floored for moonless systems.
	 *  Sizes the shadow camera frustum. */
	getSystemExtent(sysId: string): number {
		return this.moonMaxAByParent.get(sysId) ?? 0.01;
	}

	/** True if a body orbits within a planetary system, not directly around SSB/Sun. */
	isSystemBody(body: PositionedBody): boolean {
		if (isTopLevelParent(body.data.parentId)) return false;
		const parent = this.bodiesById.get(body.data.parentId);
		return parent?.data.objectType !== ObjectType.BARYCENTER;
	}

	/** True if `parentId` belongs to `sysId` — the barycenter itself or a direct child. */
	isInSystem(parentId: string, sysId: string | null): boolean {
		if (!sysId) return false;
		if (parentId === sysId) return true;
		return this.childrenByParent.get(sysId)?.has(parentId) ?? false;
	}

	/** Live bucket counts for the debug menu. */
	getObjectCounts(): {
		planets: number;
		moons: number;
		probes: number;
		earthSatellites: number;
		smallBodies: number;
	} {
		let planets = 0;
		let moons = 0;
		let probes = 0;
		for (const b of this.bodiesById.values()) {
			const t = b.data.objectType;
			if (t === ObjectType.PLANET || t === ObjectType.DWARF_PLANET) planets++;
			else if (t === ObjectType.MOON) moons++;
			else if (t === ObjectType.SPACECRAFT) probes++;
		}
		let earthSatellites = this.spacecraftByParent.get(EARTH_ID)?.size ?? 0;
		earthSatellites += this.asteroidBodiesByZone.get('earth')?.size ?? 0;
		for (const [parentId, bucket] of this.spacecraftByParent) {
			if (parentId === EARTH_ID) continue;
			probes += bucket.size;
		}
		let smallBodies = 0;
		for (const [zone, bucket] of this.asteroidBodiesByZone) {
			if (zone === 'earth') continue;
			smallBodies += bucket.size;
		}
		// Fold in standalones that arrived through bodiesById (e.g. Bennu).
		for (const b of this.bodiesById.values()) {
			if (isAsteroid(b.data.objectType) || b.data.objectType === ObjectType.COMET) smallBodies++;
		}
		return { planets, moons, probes, earthSatellites, smallBodies };
	}
}
