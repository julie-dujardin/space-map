import { SvelteMap } from 'svelte/reactivity';
import { ObjectType, ZONE_A_RANGE, type BodyData, type PositionedBody } from '$lib/types/objects';
import { ChunkLoader } from '$lib/fetch/elements/chunk';
import { AU_KM, AU_SCALE } from '../math/units';
import { orbitalElementsToPosition, parabolicToPosition } from '$lib/math/orbit/position';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';

/*
 * Visibility options:
 * CLOSE: too close to show everything, revert to point cloud.
 * FULL: show halos and trails.
 * CAPPED: In range for FULL but rejected by the crowding cap — point cloud by default, minimized halo when hideCappedMoonLabels=true.
 * FAR: point cloud.
 * HIDE: hide entirely.
 */
export enum VISIBILITY {
	CLOSE = 1,
	FULL = 2,
	CAPPED = 3,
	FAR = 4,
	HIDE = 5
}
/*
 * Distance ratio thresholds for visibility levels.
 * Ratio is (camera distance to focused body / moon semi-major axis), both in AU.
 * These were tuned for a 27" 1440p monitor; FULL and FAR are scaled at runtime by screenScaleFactor.
 */
/** Viewport height (CSS px) the distance-ratio thresholds were tuned for. */
const REFERENCE_VIEWPORT_HEIGHT = 1503;

export const PLANETARY_DISTANCE_RATIO_THRESHOLDS = {
	[VISIBILITY.CLOSE]: 0.3,
	[VISIBILITY.FULL]: 20,
	[VISIBILITY.FAR]: 100,
	[VISIBILITY.HIDE]: Infinity
};
export const SYSTEM_DISTANCE_RATIO_THRESHOLDS = {
	[VISIBILITY.CLOSE]: 0.01,
	[VISIBILITY.FULL]: 20,
	[VISIBILITY.FAR]: 100,
	[VISIBILITY.HIDE]: Infinity
};

/** Multiplier applied to the FULL threshold for the currently focused body. */
const FOCUSED_FULL_MULTIPLIER_MOON = 5;
const FOCUSED_FULL_MULTIPLIER_SPACECRAFT = 50; // TODO: check with spacecraft that orbit farther than GEO

/** Max number of moons shown at FULL visibility simultaneously. Excess (outermost) are demoted to FAR. */
export const MAX_FULL_MOONS = 25;

/** Below this distance, hide other systems (halos, orbits, spacecraft). */
export const ZOOM_THRESHOLD_AU = 0.05;

/** Shared ratio→VISIBILITY mapping used by both moon and planet/spacecraft visibility. */
function computeVisibilityFromRatio(
	ratio: number,
	thresholds: typeof PLANETARY_DISTANCE_RATIO_THRESHOLDS,
	focusedMultiplier: number,
	isFocused: boolean
): VISIBILITY {
	if (ratio <= thresholds[VISIBILITY.CLOSE]) return VISIBILITY.CLOSE;
	if (ratio <= thresholds[VISIBILITY.FULL] * (isFocused ? focusedMultiplier : 1))
		return VISIBILITY.FULL;
	if (ratio <= thresholds[VISIBILITY.FAR]) return VISIBILITY.FAR;
	return VISIBILITY.HIDE;
}

/** Map a GlobalObjectData.type string (e.g. "asteroid_main_belt") to the ObjectType enum. */
function parseObjectType(typeStr: string): ObjectType {
	const key = typeStr.toUpperCase() as keyof typeof ObjectType;
	return ObjectType[key] ?? ObjectType.UNDOCUMENTED;
}

/**
 * Create a placeholder PositionedBody from the __global__ object file.
 * Returns null if the object doesn't exist or has no orbit data.
 */
async function createPlaceholderBody(
	targetId: string,
	date: Date,
	loader: ChunkLoader
): Promise<PositionedBody | null> {
	let detail: Awaited<ReturnType<typeof fetchObjectDetail>>;
	try {
		detail = await fetchObjectDetail(targetId);
	} catch {
		console.warn(`Failed to fetch global data for ${targetId}`);
		return null;
	}
	const global = detail.global;
	if (!global?.orbit) return null;

	const orbit = global.orbit;
	const isPlanetScale = orbit.scale === 'planet';
	const isParabolic = orbit.q != null;

	const data: BodyData = {
		id: targetId,
		name: global.name ?? global.sbdb_primary_designation ?? global.provisional_designation ?? null,
		objectType: parseObjectType(global.type),
		parentId: `naif-${orbit.parent_naif_id}`,
		radiusKm: global.sbdb?.diameter ? global.sbdb.diameter / 2 : NaN,
		objectFileFlag: detail.localized ? 1 : 0,
		a: isPlanetScale ? (orbit.a ?? 0) / AU_KM : (orbit.a ?? 0),
		e: orbit.e,
		i: orbit.i,
		om: orbit.om,
		w: orbit.w,
		ma: orbit.ma ?? 0,
		n: isPlanetScale ? (orbit.n ?? 0) * 360 : (orbit.n ?? 0),
		epoch: orbit.epoch_jd,
		...(isParabolic ? { q: orbit.q, tp: orbit.tp } : {})
	};

	const parentPos = loader.positions.get(orbit.parent_naif_id) ?? [0, 0, 0];
	const offset = isParabolic
		? parabolicToPosition(data, date)
		: orbitalElementsToPosition(data, date);
	if (!offset) {
		console.warn(`Failed to compute position for ${targetId} (e=${data.e})`);
		return null;
	}
	const position: [number, number, number] = [
		parentPos[0] + offset[0],
		parentPos[1] + offset[1],
		parentPos[2] + offset[2]
	];

	return { data, position, orbitElements: data, orbitCenter: parentPos };
}

/** True if parentId is a top-level parent (SSB or Sun), not a planetary system. */
function isTopLevelParent(parentId: string): boolean {
	return parentId === 'naif-0' || parentId === 'naif-10';
}

export class ContextManager {
	private readonly childrenByParent = new Map<string, Set<string>>();
	private readonly bodiesById = new Map<string, PositionedBody>();
	/** Max semi-major axis (AU) of moons per parent body ID. Used to gate point-cloud visibility. */
	private readonly moonMaxAByParent = new Map<string, number>();

	// --- Reactive loading state ($state safe: only mutated during async load, never in useTask) ---
	loading = $state(true);
	error = $state<string | null>(null);
	majorBodies = $state<PositionedBody[]>([]);
	asteroidBodiesByZone = $state(new SvelteMap<string, PositionedBody[]>());
	spacecraftByParent = $state(new SvelteMap<string, PositionedBody[]>());

	/** Zones/groups that received new data since last rebuild. Cleared by the consumer. */
	dirtyAsteroidZones = new Set<string>();
	dirtySpacecraftGroups = new Set<string>();

	// --- Visibility state (plain mutable: written from useTask every frame) ---
	focusedBodyId: string = 'naif-10'; // default to sun (not set by this class)
	isZoomedIn: boolean = false;
	private lastRecomputeDist = -1;
	/** Always set from focused body — drives moon visibility regardless of zoom. */
	focusedSystemId: string | null = null;
	/** Set only when zoomed in — drives hiding of other systems. */
	activeSystemId: string | null = null;
	private cameraDistThreeJS = 0;
	// Cached scaled thresholds — recomputed in updateViewport() on canvas resize.
	private scaledPlanetary = PLANETARY_DISTANCE_RATIO_THRESHOLDS;
	private scaledSystem = SYSTEM_DISTANCE_RATIO_THRESHOLDS;
	/** IDs of moons allowed FULL visibility after the crowding cap is applied. */
	private fullMoonIds = new Set<string>();
	/** Per-frame cache for getMoonVisibility, cleared in updateCamera. */
	private moonVisibilityCache = new Map<string, VISIBILITY>();

	/**
	 * Look up any body by ID. Checks the major-body index first,
	 * then falls back to a linear scan of asteroid/spacecraft zone maps.
	 */
	getBody(id: string): PositionedBody | undefined {
		const major = this.bodiesById.get(id);
		if (major) return major;
		for (const bodies of this.asteroidBodiesByZone.values()) {
			const hit = bodies.find((b) => b.data.id === id);
			if (hit) return hit;
		}
		for (const bodies of this.spacecraftByParent.values()) {
			const hit = bodies.find((b) => b.data.id === id);
			if (hit) return hit;
		}
		return undefined;
	}

	async load(date: Date, targetId?: string): Promise<void> {
		try {
			const loader = new ChunkLoader();

			// Kick off moons + metadata fetches immediately, in parallel with major processing.
			// Once metadata arrives, fire all chunk prefetches so they're cached before Phase 2 starts.
			ChunkLoader.prefetch('moons', 0, 0);
			const minorChunkArgsPromise = fetch('/data/v1/metadata.json')
				.then((r) => {
					if (!r.ok) throw new Error(`Failed to fetch metadata: ${r.status}`);
					return r.json();
				})
				.then(
					(metadata: { zones: Record<string, { zooms: Record<string, { parts: number }> }> }) => {
						const args: { zone: string; zoom: number; part: number }[] = [];
						for (const [zone, zoneData] of Object.entries(metadata.zones) as [
							string,
							{ zooms: Record<string, { parts: number }> }
						][]) {
							for (const [zoomStr, zoomData] of Object.entries(zoneData.zooms) as [
								string,
								{ parts: number }
							][]) {
								if (zone !== 'major' && zone !== 'moons')
									for (let part = 0; part < Math.min(zoomData.parts, 20); part++) {
										args.push({ zone, zoom: Number(zoomStr), part });
										ChunkLoader.prefetch(zone, Number(zoomStr), part);
									}
							}
						}
						return args;
					}
				);

			// Phase 1: majors — load, register, and start rendering immediately
			const major: PositionedBody[] = [];
			major.push(...(await loader.process('major', 0, 0, date)));
			major.push(...(await loader.process('moons', 0, 0, date)));

			this.addBodies(major);

			// If the target body wasn't in majors/moons, resolve it from the global object file
			// so the renderer can focus on it immediately without waiting for its element chunk.
			if (targetId && !this.getBody(targetId)) {
				const placeholder = await createPlaceholderBody(targetId, date, loader);
				if (placeholder) this.addBodies([placeholder]);
			}

			this.majorBodies = major.filter(
				(b) =>
					b.data.objectType !== ObjectType.BARYCENTER &&
					b.data.objectType !== ObjectType.LAGRANGE_POINT
			);
			this.loading = false;

			// Phase 2: minors — load in background, flush to reactive state periodically
			// minorChunkArgsPromise has been running in parallel; files are likely cached already
			const minorChunkArgs = await minorChunkArgsPromise;

			const pendingAsteroids = new SvelteMap<string, PositionedBody[]>();
			const pendingSpacecraft = new SvelteMap<string, PositionedBody[]>();

			const flush = () => {
				this.asteroidBodiesByZone = new SvelteMap(pendingAsteroids);
				this.spacecraftByParent = new SvelteMap(pendingSpacecraft);
			};
			const intervalId = setInterval(flush, 500);

			try {
				await Promise.all(
					minorChunkArgs.map(({ zone, zoom, part }) =>
						loader.process(zone, zoom, part, date).then((chunk) => {
							for (const b of chunk) {
								if (b.data.objectType === ObjectType.SPACECRAFT) {
									const list = pendingSpacecraft.get(b.data.parentId) ?? [];
									list.push(b);
									pendingSpacecraft.set(b.data.parentId, list);
									this.dirtySpacecraftGroups.add(b.data.parentId);
								} else {
									const list = pendingAsteroids.get(zone) ?? [];
									list.push(b);
									pendingAsteroids.set(zone, list);
									this.dirtyAsteroidZones.add(zone);
								}
							}
						})
					)
				);
			} finally {
				clearInterval(intervalId);
				flush();
			}
		} catch (e) {
			this.loading = false;
			throw e;
		}
	}

	addBodies(bodies: PositionedBody[]): void {
		for (const b of bodies) {
			this.bodiesById.set(b.data.id, b);

			const set = this.childrenByParent.get(b.data.parentId) ?? new Set<string>();
			set.add(b.data.id);
			this.childrenByParent.set(b.data.parentId, set);
			if (b.data.objectType === ObjectType.MOON) {
				const prev = this.moonMaxAByParent.get(b.data.parentId) ?? 0;
				if (b.data.a > prev) this.moonMaxAByParent.set(b.data.parentId, b.data.a);
			}
		}
	}

	/**
	 * Call from resize() in SceneRenderer whenever the canvas dimensions change.
	 * Recomputes scaled thresholds (FULL and FAR scale linearly; CLOSE is geometric and unchanged).
	 */
	updateViewport(height: number): void {
		const sf = (height / REFERENCE_VIEWPORT_HEIGHT) ** 1.5;
		const scale = (base: typeof PLANETARY_DISTANCE_RATIO_THRESHOLDS) => ({
			...base,
			[VISIBILITY.FULL]: base[VISIBILITY.FULL] * sf,
			[VISIBILITY.FAR]: base[VISIBILITY.FAR] * sf
		});
		this.scaledPlanetary = scale(PLANETARY_DISTANCE_RATIO_THRESHOLDS);
		this.scaledSystem = scale(SYSTEM_DISTANCE_RATIO_THRESHOLDS);
	}

	/** Call from useTask every frame. */
	updateCamera(dist: number): void {
		this.cameraDistThreeJS = dist;
		this.moonVisibilityCache.clear();
		const zoomed = dist <= ZOOM_THRESHOLD_AU * AU_SCALE;
		if (zoomed !== this.isZoomedIn) {
			this.isZoomedIn = zoomed;
			this.activeSystemId = this.isZoomedIn ? this.focusedSystemId : null;
		}
		// Only recompute when distance changes by more than 0.5% — avoids a filter+sort every frame
		if (Math.abs(dist - this.lastRecomputeDist) > this.lastRecomputeDist * 0.005 + 0.001) {
			this.lastRecomputeDist = dist;
			this.recomputeFullMoons();
		}
	}

	setFocused(body: PositionedBody): void {
		if (body.data.id !== this.focusedBodyId) {
			this.focusedBodyId = body.data.id;
			// A planetary barycenter IS the system root (planets/moons are its children),
			// but the SSB (naif-0) is top-level, not a system.
			const isSystemBarycenter =
				body.data.objectType === ObjectType.BARYCENTER &&
				isTopLevelParent(body.data.parentId) &&
				!isTopLevelParent(body.data.id);
			const isTopLevel =
				body.data.objectType === ObjectType.STAR ||
				(!isSystemBarycenter && isTopLevelParent(body.data.parentId));
			this.focusedSystemId = isSystemBarycenter
				? body.data.id
				: isTopLevel
					? null
					: body.data.parentId;
			this.activeSystemId = this.isZoomedIn ? this.focusedSystemId : null;
			this.lastRecomputeDist = -1; // force recompute on next updateCamera
			this.recomputeFullMoons();
		}
	}

	/** Ratio-based visibility for a moon. Gated on the focused system (no zoom threshold). */
	getMoonVisibility(moon: PositionedBody): VISIBILITY {
		const cached = this.moonVisibilityCache.get(moon.data.id);
		if (cached !== undefined) return cached;
		let vis: VISIBILITY;
		if (!this.isInFocusedSystem(moon.data.parentId)) {
			vis = VISIBILITY.HIDE;
		} else {
			const ratio = this.cameraDistThreeJS / AU_SCALE / moon.data.a; // Three.js units → AU
			const isFocused = moon.data.id === this.focusedBodyId;
			vis = computeVisibilityFromRatio(
				ratio,
				this.scaledPlanetary,
				FOCUSED_FULL_MULTIPLIER_MOON,
				isFocused
			);
			// Crowding cap: demote FULL → CAPPED if not in the top-N set
			if (vis === VISIBILITY.FULL && !this.fullMoonIds.has(moon.data.id) && !isFocused)
				vis = VISIBILITY.CAPPED;
		}
		this.moonVisibilityCache.set(moon.data.id, vis);
		return vis;
	}

	/**
	 * Recomputes which moons qualify for FULL visibility, capped at MAX_FULL_MOONS.
	 * Among moons that pass the ratio threshold, only the closest to their parent (smallest a) win.
	 * Called every frame from updateCamera and on focus change from setFocused.
	 */
	private recomputeFullMoons(): void {
		this.fullMoonIds.clear();
		const sysId = this.focusedSystemId;
		if (!sysId) return;
		const camDistAU = this.cameraDistThreeJS / AU_SCALE;
		const children: PositionedBody[] = [];
		for (const id of this.childrenByParent.get(sysId) ?? []) {
			const b = this.bodiesById.get(id);
			if (
				b &&
				b.data.objectType === ObjectType.MOON &&
				camDistAU / b.data.a <= this.scaledPlanetary[VISIBILITY.FULL]
			)
				children.push(b);
		}
		children
			.sort((a, b) => a.data.a - b.data.a)
			.slice(0, MAX_FULL_MOONS)
			.forEach((m) => this.fullMoonIds.add(m.data.id));
	}

	/**
	 * Whether to show the point-cloud for a moon group (by parent ID).
	 * Gated on the focused system and ratio to outermost moon (no zoom threshold).
	 */
	isMoonGroupVisible(parentId: string): boolean {
		if (!this.isInFocusedSystem(parentId)) return false;
		const maxA = this.moonMaxAByParent.get(parentId);
		if (!maxA) return false;
		const ratio = this.cameraDistThreeJS / AU_SCALE / maxA;
		return ratio <= this.scaledPlanetary[VISIBILITY.FAR];
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
	 * Distance-ratio based visibility for non-moon, non-star bodies.
	 * Bodies orbiting a planet (spacecraft, debris) are gated on the focused system,
	 * like moons. Sun-orbiting bodies use the solar-orbit semi-major axis ratio.
	 * Spacecraft use distance to focused body (like moons) so they appear/disappear
	 * uniformly by zoom level; planets use distance to the body itself.
	 */
	getPlanetVisibility(body: PositionedBody, camDistThreeJS: number): VISIBILITY {
		// Planet-orbiting bodies: only visible when their system is focused.
		if (this.isSystemBody(body)) {
			if (!this.isInFocusedSystem(body.data.parentId)) return VISIBILITY.HIDE;
			return VISIBILITY.FULL;
		}

		// Sun-orbiting: walk up to the barycenter to find solar-orbit semi-major axis.
		let refA = body.data.a;
		if (!isTopLevelParent(body.data.parentId)) {
			const parent = this.bodiesById.get(body.data.parentId);
			if (parent?.data.a) refA = parent.data.a;
		}
		if (!refA || refA < 0) {
			if (refA >= 0 && body.data.e < 0.9) {
				console.log(
					`No semi-major axis available for body ${body.data.id} (${body.data.name}), falling back to FULL visibility`
				);
			}
			return VISIBILITY.FULL;
		}
		// Spacecraft use distance to focused body (uniform visibility by zoom level),
		// planets use distance to the body itself.
		const dist =
			body.data.objectType === ObjectType.SPACECRAFT ? this.cameraDistThreeJS : camDistThreeJS;
		const isFocused = body.data.id === this.focusedBodyId;
		return computeVisibilityFromRatio(
			dist / AU_SCALE / refA,
			this.scaledSystem,
			FOCUSED_FULL_MULTIPLIER_SPACECRAFT,
			isFocused
		);
	}

	/** Full rendering = halo + trail. Suppressed for out-of-system bodies when zoomed in. */
	hasFullRendering(body: PositionedBody): boolean {
		const sysId = this.activeSystemId;
		if (!sysId) return true;
		return this.isInActiveSystem(
			isTopLevelParent(body.data.parentId) ? body.data.id : body.data.parentId
		);
	}

	/**
	 * Whether a spacecraft point-cloud group should be shown.
	 * Sun-level groups (parentId=0 or parent is STAR) are always visible.
	 * Planet-orbiting groups are only visible when in the active system.
	 */
	isSpacecraftGroupVisible(groupParentId: string): boolean {
		const sysId = this.activeSystemId;
		if (isTopLevelParent(groupParentId)) return !sysId;
		const parent = this.bodiesById.get(groupParentId);
		if (parent?.data.objectType === ObjectType.STAR) return !sysId;
		if (!sysId) return false;
		if (groupParentId === sysId) return true;
		return this.childrenByParent.get(sysId)?.has(groupParentId) ?? false;
	}

	/**
	 * Whether an asteroid zone's point-cloud should be visible.
	 * Compares camera distance (AU) to the zone's semi-major axis range.
	 * Zones without a defined range (parabolic, unclassified) are always visible.
	 */
	isAsteroidGroupVisible(zone: string): boolean {
		if (this.activeSystemId) return false;
		const range = ZONE_A_RANGE[zone];
		if (!range) return true;
		const camDistAU = this.cameraDistThreeJS / AU_SCALE;
		const ratio = camDistAU / range.maxA;
		// reduce clutter by lowering threshold a bit
		return ratio <= this.scaledSystem[VISIBILITY.FAR] / 3;
	}

	/** Max orbital semi-major axis (AU) of moons in a system. Used to size the shadow camera frustum. */
	getSystemExtent(sysId: string): number {
		return this.moonMaxAByParent.get(sysId) ?? 0.01;
	}

	isInActiveSystem(parentId: string): boolean {
		return this.isInSystem(parentId, this.activeSystemId);
	}

	private isInFocusedSystem(parentId: string): boolean {
		return this.isInSystem(parentId, this.focusedSystemId);
	}

	/**
	 * True if the given parentId belongs to a system.
	 * Handles two levels: parentId === barycenter, or parentId is a direct child of the barycenter.
	 */
	private isInSystem(parentId: string, sysId: string | null): boolean {
		if (!sysId) return false;
		if (parentId === sysId) return true;
		return this.childrenByParent.get(sysId)?.has(parentId) ?? false;
	}
}
