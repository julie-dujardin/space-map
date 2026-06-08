import { ObjectType, isAsteroid, type PositionedBody } from '$lib/types/objects';
import { EARTH_ID, SSB_ID, SUN_ID } from '$lib/constants';

/** True if parentId is a top-level parent (SSB or Sun), not a planetary system. */
export function isTopLevelParent(parentId: string): boolean {
	return parentId === SSB_ID || parentId === SUN_ID;
}

/**
 * The scene's body store. Owns every loaded `PositionedBody` plus the
 * parent/child graph used to answer system-membership questions. Visibility
 * decisions and per-frame loops read from here; loaders (initial chunk fetch
 * + hot-reload) write through here.
 */
export class BodyIndex {
	/** All major-tier bodies (chebyshev majors, kepler majors, moons, URL-loaded
	 *  placeholders, standalones). Keyed by object id. */
	readonly bodiesById = new Map<string, PositionedBody>();

	/** Promoted-for-render subset of `bodiesById`. Barycenters, Lagrange points,
	 *  and SPICE-probe entries are excluded — the renderer's hot loops walk
	 *  this so the long tail of probes stays out of per-frame iteration. */
	majorBodies: PositionedBody[] = [];

	/** Per-zone asteroid buckets — inner Map keyed by object id so `getBody`/
	 *  zone-local lookups stay O(1) without duplicating refs into a flat index. */
	asteroidBodiesByZone = new Map<string, Map<string, PositionedBody>>();

	/** Per-parent spacecraft buckets — same shape as `asteroidBodiesByZone`,
	 *  outer key is the parent id (e.g. `naif-399` for Earth sats). */
	spacecraftByParent = new Map<string, Map<string, PositionedBody>>();

	/** Zones/groups that received new data since last rebuild. Cleared by the consumer. */
	dirtyAsteroidZones = new Set<string>();
	dirtySpacecraftGroups = new Set<string>();

	/** Incremented on each minor-body data flush; read by Scene.svelte to trigger point cloud rebuilds. */
	minorBodyVersion = $state(0);

	/** Bumped by the renderer after `loadSystemData` lands a system's metadata
	 *  (which is what attaches `orientation` to PositionedBody). Lets reactive
	 *  consumers — currently the compass-north choice list — recompute as
	 *  pole data arrives, since orientation is a property mutation on the
	 *  existing `$state.raw` body and wouldn't otherwise re-trigger derived. */
	orientationVersion = $state(0);

	/** Parent → children index (object ids only). Built incrementally as
	 *  bodies are added; used to answer system-membership questions in O(1). */
	private readonly childrenByParent = new Map<string, Set<string>>();

	/** Max semi-major axis (AU) of moons per parent body id. Used to size the
	 *  shadow camera frustum and to gate point-cloud visibility. */
	private readonly moonMaxAByParent = new Map<string, number>();

	/** Subscribers notified after any bucket gains new ids — drives promotion
	 *  matching without per-frame zone scans. */
	private readonly addListeners = new Set<(ids: readonly string[]) => void>();

	/** Subscribe to bulk additions across any bucket (bodiesById, zone buckets,
	 *  spacecraft buckets). The callback fires with the freshly-added ids only;
	 *  updates to existing entries are not announced. */
	onBodiesAdded(cb: (ids: readonly string[]) => void): () => void {
		this.addListeners.add(cb);
		return () => this.addListeners.delete(cb);
	}

	/** Fire `onBodiesAdded` listeners. Called by `addBodies` for bodiesById
	 *  insertions, and directly by loaders that mutate the zone buckets
	 *  (scene-load flush, zone-refresher merges). */
	notifyBodiesAdded(ids: readonly string[]): void {
		if (ids.length === 0 || this.addListeners.size === 0) return;
		for (const cb of this.addListeners) cb(ids);
	}

	/**
	 * Look up any body by ID. Pass `zone` (parent id for spacecraft groups,
	 * OrbitClass name for asteroid zones) when you already know the bucket —
	 * skips the linear scan. Without a hint: bodiesById → spacecraftByParent →
	 * asteroidBodiesByZone.
	 */
	getBody(id: string, zone?: string): PositionedBody | undefined {
		const major = this.bodiesById.get(id);
		if (major) return major;
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

	/** Register a batch of bodies. Updates `bodiesById`, the parent/child
	 *  index, and the per-parent moon-max-a tracker. Orbit-source attribution
	 *  is the caller's responsibility (see CreditsStore.recordOrbitSources). */
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

	/** Zone holding an asteroid/comet body (e.g. `small_bodies/MBA`,
	 *  `small_body_moons`, `earth`), or undefined for non-belt bodies. Linear
	 *  scan across zone buckets — fine for the promoted-body cardinality the
	 *  visibility loop and promotion bookkeeping run on. */
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

	/** Max orbital semi-major axis (AU) of moons in a system, with a safe
	 *  floor for systems with no moons. Used to size the shadow camera frustum. */
	getSystemExtent(sysId: string): number {
		return this.moonMaxAByParent.get(sysId) ?? 0.01;
	}

	/**
	 * Whether a body orbits within a planetary system (not directly around SSB/Sun).
	 * True for moons, planet-orbiting spacecraft, etc.
	 */
	isSystemBody(body: PositionedBody): boolean {
		if (isTopLevelParent(body.data.parentId)) return false;
		const parent = this.bodiesById.get(body.data.parentId);
		return parent?.data.objectType !== ObjectType.BARYCENTER;
	}

	/**
	 * True if the given parentId belongs to a system.
	 * Handles two levels: parentId === barycenter, or parentId is a direct child of the barycenter.
	 */
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
		// Standalone asteroids/comets that arrived through bodiesById (URL-loaded
		// placeholders or major chunks) — fold them into the small-body count so
		// e.g. Bennu shows up.
		for (const b of this.bodiesById.values()) {
			if (isAsteroid(b.data.objectType) || b.data.objectType === ObjectType.COMET) smallBodies++;
		}
		return { planets, moons, probes, earthSatellites, smallBodies };
	}
}
