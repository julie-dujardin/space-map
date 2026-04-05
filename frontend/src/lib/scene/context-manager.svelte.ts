import { SvelteMap, SvelteSet } from 'svelte/reactivity';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { ChunkLoader } from '$lib/fetch/elements/chunk';
import { AU_SCALE } from '../math/units';

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

/** Max number of moons shown at FULL visibility simultaneously. Excess (outermost) are demoted to FAR. */
export const MAX_FULL_MOONS = 25;

/** Below this distance, hide other systems (halos, orbits, spacecraft). */
export const ZOOM_THRESHOLD_AU = 0.3;

export class ContextManager {
	private readonly childrenByParent = new SvelteMap<string, PositionedBody[]>();
	private readonly bodiesById = new SvelteMap<string, PositionedBody>();
	/** Max semi-major axis (AU) of moons per parent body ID. Used to gate point-cloud visibility. */
	private readonly moonMaxAByParent = new SvelteMap<string, number>();

	// --- Reactive loading state ($state safe: only mutated during async load, never in useTask) ---
	loading = $state(true);
	error = $state<string | null>(null);
	majorBodies = $state<PositionedBody[]>([]);
	asteroidBodies = $state<PositionedBody[]>([]);
	spacecraftByParent = $state(new SvelteMap<string, PositionedBody[]>());

	// --- Visibility state (plain mutable: written from useTask every frame) ---
	focusedBodyId: string = 'naif-10'; // default to sun (not set by this class)
	isZoomedIn: boolean = false;
	/** Always set from focused body — drives moon visibility regardless of zoom. */
	focusedSystemId: string | null = null;
	/** Set only when zoomed in — drives hiding of other systems. */
	activeSystemId: string | null = null;
	private cameraDistThreeJS = 0;
	// Cached scaled thresholds — recomputed in updateViewport() on canvas resize.
	private scaledPlanetary = PLANETARY_DISTANCE_RATIO_THRESHOLDS;
	private scaledSystem = SYSTEM_DISTANCE_RATIO_THRESHOLDS;
	/** IDs of moons allowed FULL visibility after the crowding cap is applied. */
	private fullMoonIds = new SvelteSet<string>();

	get allBodies(): PositionedBody[] {
		return [...this.bodiesById.values()];
	}

	async load(date: Date): Promise<void> {
		try {
			const loader = new ChunkLoader();

			// Phase 1: majors — load, register, and start rendering immediately
			const major: PositionedBody[] = [];
			major.push(...(await loader.process('major', 0, 0, date)));
			major.push(...(await loader.process('moons', 0, 0, date)));

			this.addBodies(major);
			this.majorBodies = major.filter(
				(b) =>
					b.data.objectType !== ObjectType.BARYCENTER &&
					b.data.objectType !== ObjectType.LAGRANGE_POINT
			);
			this.loading = false;

			// Phase 2: minors — load in background, flush to reactive state periodically
			const metaRes = await fetch('/data/v1/metadata.json');
			if (!metaRes.ok) throw new Error(`Failed to fetch metadata: ${metaRes.status}`);
			const metadata = await metaRes.json();

			const minorChunkArgs: { zone: string; zoom: number; part: number }[] = [];
			for (const [zone, zoneData] of Object.entries(metadata.zones) as [
				string,
				{ zooms: Record<string, { parts: number }> }
			][]) {
				for (const [zoomStr, zoomData] of Object.entries(zoneData.zooms) as [
					string,
					{ parts: number }
				][]) {
					if (zone !== 'major' && zone !== 'moons')
						for (let part = 0; part < Math.min(zoomData.parts, 20); part++)
							minorChunkArgs.push({ zone, zoom: Number(zoomStr), part });
				}
			}

			const pendingAsteroids: PositionedBody[] = [];
			const pendingSpacecraft = new SvelteMap<string, PositionedBody[]>();

			const flush = () => {
				this.asteroidBodies = [...pendingAsteroids];
				this.spacecraftByParent = new SvelteMap(pendingSpacecraft);
			};
			const intervalId = setInterval(flush, 500);

			try {
				await Promise.all(
					minorChunkArgs.map(({ zone, zoom, part }) =>
						loader.process(zone, zoom, part, date).then((chunk) => {
							this.addBodies(chunk);
							for (const b of chunk) {
								if (b.data.objectType === ObjectType.SPACECRAFT) {
									const list = pendingSpacecraft.get(b.data.parentId) ?? [];
									list.push(b);
									pendingSpacecraft.set(b.data.parentId, list);
								} else {
									pendingAsteroids.push(b);
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
			const list = this.childrenByParent.get(b.data.parentId) ?? [];
			list.push(b);
			this.childrenByParent.set(b.data.parentId, list);
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
		const zoomed = dist <= ZOOM_THRESHOLD_AU * AU_SCALE;
		if (zoomed !== this.isZoomedIn) {
			this.isZoomedIn = zoomed;
			this.activeSystemId = this.isZoomedIn ? this.focusedSystemId : null;
		}
		this.recomputeFullMoons();
	}

	setFocused(body: PositionedBody): void {
		if (body.data.id !== this.focusedBodyId) {
			this.focusedBodyId = body.data.id;
			// System ID is either the parent (for moons or planet that orbit a barycenter), or the body's own ID (for venus, ceres...)
			this.focusedSystemId =
				body.data.objectType === ObjectType.STAR
					? null
					: body.data.parentId !== 'naif-0'
						? body.data.parentId
						: body.data.id;
			this.activeSystemId = this.isZoomedIn ? this.focusedSystemId : null;
			this.recomputeFullMoons();
		}
	}

	/** Ratio-based visibility for a moon. Gated on the focused system (no zoom threshold). */
	getMoonVisibility(moon: PositionedBody): VISIBILITY {
		if (!this.isInFocusedSystem(moon.data.parentId)) return VISIBILITY.HIDE;
		const ratio = this.cameraDistThreeJS / AU_SCALE / moon.data.a; // Three.js units → AU
		if (ratio <= this.scaledPlanetary[VISIBILITY.CLOSE]) return VISIBILITY.CLOSE;
		if (ratio <= this.scaledPlanetary[VISIBILITY.FULL])
			return this.fullMoonIds.has(moon.data.id) ? VISIBILITY.FULL : VISIBILITY.CAPPED;
		if (ratio <= this.scaledPlanetary[VISIBILITY.FAR]) return VISIBILITY.FAR;
		return VISIBILITY.HIDE;
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
		(this.childrenByParent.get(sysId) ?? [])
			.filter(
				(b) =>
					b.data.objectType === ObjectType.MOON &&
					camDistAU / b.data.a <= this.scaledPlanetary[VISIBILITY.FULL]
			)
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
	 * Distance-ratio based visibility for non-moon, non-star bodies (planets, dwarf planets…).
	 * Ratio is (camera distance to the body / body semi-major axis), both in AU.
	 * Falls back to FULL when no orbital data is available.
	 */
	getPlanetVisibility(body: PositionedBody, camDistThreeJS: number): VISIBILITY {
		// Determine the effective solar-orbit semi-major axis for the ratio:
		// - Body orbits SSB directly (parentId=0): use body.data.a
		// - Body orbits a barycenter with a>0 (e.g. EMB at ~1 AU): use barycenter's a
		// - Body orbits a barycenter with a=0 (e.g. Mars bary): fall back to body.data.a
		let refA = body.data.a;
		if (body.data.parentId !== 'naif-0') {
			const parent = this.bodiesById.get(body.data.parentId);
			if (parent) {
				if (parent.data.a) refA = parent.data.a;
			}
		}
		if (!refA) {
			console.log(
				`No semi-major axis available for body ${body.data.id} (${body.data.name}), falling back to FULL visibility`
			);
			return VISIBILITY.FULL;
		}
		const ratio = camDistThreeJS / AU_SCALE / refA;
		if (ratio <= this.scaledSystem[VISIBILITY.CLOSE]) return VISIBILITY.CLOSE;
		if (ratio <= this.scaledSystem[VISIBILITY.FULL]) return VISIBILITY.FULL;
		if (ratio <= this.scaledSystem[VISIBILITY.FAR]) return VISIBILITY.FAR;
		return VISIBILITY.HIDE;
	}

	/** Full rendering = halo + trail. Suppressed for out-of-system bodies when zoomed in. */
	hasFullRendering(body: PositionedBody): boolean {
		const sysId = this.activeSystemId;
		if (!sysId) return true;
		return this.isInActiveSystem(
			body.data.parentId !== 'naif-0' ? body.data.parentId : body.data.id
		);
	}

	/**
	 * Whether a spacecraft point-cloud group should be shown.
	 * Sun-level groups (parentId=0 or parent is STAR) are always visible.
	 * Planet-orbiting groups are only visible when in the active system.
	 */
	isSpacecraftGroupVisible(groupParentId: string): boolean {
		if (groupParentId === 'naif-0') return true;
		const parent = this.bodiesById.get(groupParentId);
		if (parent?.data.objectType === ObjectType.STAR) return true;
		const sysId = this.activeSystemId;
		if (!sysId) return false;
		if (groupParentId === sysId) return true;
		return (this.childrenByParent.get(sysId) ?? []).some((c) => c.data.id === groupParentId);
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
		return (this.childrenByParent.get(sysId) ?? []).some((c) => c.data.id === parentId);
	}
}
