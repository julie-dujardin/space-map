import { ObjectType, ZONE_A_RANGE, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { AU_SCALE } from '$lib/math/units';
import { BodyIndex, isTopLevelParent } from '$lib/scene/state/bodies.svelte';
import {
	VISIBILITY,
	REFERENCE_VIEWPORT_HEIGHT,
	PLANETARY_DISTANCE_RATIO_THRESHOLDS,
	SYSTEM_DISTANCE_RATIO_THRESHOLDS,
	FOCUSED_FULL_MULTIPLIER_MOON,
	FOCUSED_FULL_MULTIPLIER_SPACECRAFT,
	MAX_FULL_MOONS,
	computeVisibilityFromRatio,
	ZOOM_THRESHOLD_AU
} from '$lib/scene/visibility/thresholds';

/**
 * Owns focus state and turns camera distance + focus into per-body visibility
 * decisions. Reads body topology (parent/child graph, moon extents) from
 * {@link BodyIndex}; produces VISIBILITY values that `visibility/update.ts`
 * and `visibility/flags.ts` translate into Three.js side effects.
 *
 * Two parallel focus mirrors: `focusedBodyId`/`focusedSystemId` are reactive
 * (`$state`) for Svelte consumers (attribution bar, popover); the `*Plain`
 * variants are plain fields read by hot per-frame loops, where every `$state`
 * getter would otherwise fire a reactive-source tag + proxy trap.
 */
export class VisibilityController {
	/**
	 * Currently focused body. Reactive so the attribution bar can show texture
	 * credits for standalone bodies (asteroids like Bennu, dwarf planets like
	 * Ceres) that aren't part of a loaded planetary system.
	 */
	focusedBodyId = $state<string>('naif-10');
	/**
	 * Always set from focused body — drives moon visibility regardless of zoom.
	 * Reactive so the attribution bar can derive the active imagery credits
	 * from whichever planetary system the camera is in.
	 */
	focusedSystemId = $state<string | null>(null);
	/** Set only when zoomed in — drives hiding of other systems. */
	activeSystemId: string | null = null;
	isZoomedIn = false;

	// Plain mirrors of the reactive focus fields above. Hot per-frame loops
	// (visibility, sphere/texture LOD, ring shaders) read these instead of the
	// $state-tracked versions — in dev mode every $state getter fires a
	// reactive-source tag + `get_proxied_value` trap, and the per-body loops
	// turned that into the dominant cost.
	private focusedBodyIdPlain: string = 'naif-10';
	private focusedSystemIdPlain: string | null = null;
	private cameraDistThreeJS = 0;
	private lastRecomputeDist = -1;
	// Cached scaled thresholds — recomputed in updateViewport() on canvas resize.
	private scaledPlanetary = PLANETARY_DISTANCE_RATIO_THRESHOLDS;
	private scaledSystem = SYSTEM_DISTANCE_RATIO_THRESHOLDS;
	/** IDs of moons allowed FULL visibility after the crowding cap is applied. */
	private fullMoonIds = new Set<string>();
	/** Per-frame cache for getMoonVisibility, cleared in updateCamera. */
	private moonVisibilityCache = new Map<string, VISIBILITY>();

	constructor(private readonly bodies: BodyIndex) {}

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
			this.activeSystemId = this.isZoomedIn ? this.focusedSystemIdPlain : null;
		}
		// Only recompute when distance changes by more than 0.5% — avoids a filter+sort every frame
		if (Math.abs(dist - this.lastRecomputeDist) > this.lastRecomputeDist * 0.005 + 0.001) {
			this.lastRecomputeDist = dist;
			this.recomputeFullMoons();
		}
	}

	setFocused(body: PositionedBody): void {
		if (body.data.id === this.focusedBodyIdPlain) return;
		this.focusedBodyId = body.data.id;
		this.focusedBodyIdPlain = body.data.id;
		// A planetary barycenter IS the system root (planets/moons are its children),
		// but the SSB (naif-0) is top-level, not a system.
		const isSystemBarycenter =
			body.data.objectType === ObjectType.BARYCENTER &&
			isTopLevelParent(body.data.parentId) &&
			!isTopLevelParent(body.data.id);
		const isTopLevel =
			body.data.objectType === ObjectType.STAR ||
			(!isSystemBarycenter && isTopLevelParent(body.data.parentId));
		let sysId: string | null;
		if (isSystemBarycenter) {
			sysId = body.data.id;
		} else if (isTopLevel) {
			sysId = null;
		} else {
			// parentId is either the system barycenter (e.g. Earth's parent is naif-3) or
			// a system member one level deeper (e.g. an Earth satellite's parent is naif-399,
			// whose parent is naif-3). Satellites aren't recorded as barycenter children
			// — too many — so resolve by walking up via bodiesById instead.
			const parent = this.bodies.bodiesById.get(body.data.parentId);
			sysId =
				parent && !isTopLevelParent(parent.data.parentId)
					? parent.data.parentId
					: body.data.parentId;
		}
		this.focusedSystemId = sysId;
		this.focusedSystemIdPlain = sysId;
		this.activeSystemId = this.isZoomedIn ? sysId : null;
		this.lastRecomputeDist = -1; // force recompute on next updateCamera
		this.recomputeFullMoons();
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
			const isFocused = moon.data.id === this.focusedBodyIdPlain;
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
	 * Distance-ratio based visibility for non-moon, non-star bodies.
	 * Bodies orbiting a planet (spacecraft, debris) are gated on the focused system,
	 * like moons. Sun-orbiting bodies use the solar-orbit semi-major axis ratio.
	 * Spacecraft use distance to focused body (like moons) so they appear/disappear
	 * uniformly by zoom level; planets use distance to the body itself.
	 */
	getPlanetVisibility(body: PositionedBody, camDistThreeJS: number): VISIBILITY {
		// Planet-orbiting bodies: only visible when their system is focused.
		if (this.bodies.isSystemBody(body)) {
			if (!this.isInFocusedSystem(body.data.parentId)) return VISIBILITY.HIDE;
			return VISIBILITY.FULL;
		}

		// Probes carry a=0 by design — their positions come from per-sub-chunk
		// methods (kepler_pure/drift/chebyshev), not an osculating ellipse — so
		// approximate refA from the current body→parent distance (≈ semi-major
		// axis for near-circular orbits, which most probes follow once captured;
		// cruise probes parent on the Sun and end up with a heliocentric-scale
		// refA naturally).
		let refA: number;
		if (body.data.orbitalSource === OrbitalSource.SPICE_PROBE) {
			const parent = this.bodies.bodiesById.get(body.data.parentId);
			if (!parent) return VISIBILITY.FULL;
			const dx = body.position[0] - parent.position[0];
			const dy = body.position[1] - parent.position[1];
			const dz = body.position[2] - parent.position[2];
			refA = Math.sqrt(dx * dx + dy * dy + dz * dz) / AU_SCALE / 2;
		} else {
			// Sun-orbiting: walk up to the barycenter to find solar-orbit semi-major axis.
			refA = body.data.a;
			if (!isTopLevelParent(body.data.parentId)) {
				const parent = this.bodies.bodiesById.get(body.data.parentId);
				if (parent?.data.a) refA = parent.data.a;
			}
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
		const isFocused = body.data.id === this.focusedBodyIdPlain;
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
	 * Whether to show the point-cloud for a moon group (by parent ID).
	 * Gated on the focused system and ratio to outermost moon (no zoom threshold).
	 */
	isMoonGroupVisible(parentId: string): boolean {
		if (!this.isInFocusedSystem(parentId)) return false;
		const maxA = this.bodies.maxMoonA(parentId);
		if (!maxA) return false;
		const ratio = this.cameraDistThreeJS / AU_SCALE / maxA;
		return ratio <= this.scaledPlanetary[VISIBILITY.FAR];
	}

	/**
	 * Whether a spacecraft point-cloud group should be shown.
	 * Sun-level groups (parentId=0 or parent is STAR) are always visible.
	 * Planet-orbiting groups are only visible when in the active system.
	 */
	isSpacecraftGroupVisible(groupParentId: string): boolean {
		const sysId = this.activeSystemId;
		if (isTopLevelParent(groupParentId)) return !sysId;
		const parent = this.bodies.bodiesById.get(groupParentId);
		if (parent?.data.objectType === ObjectType.STAR) return !sysId;
		if (!sysId) return false;
		if (groupParentId === sysId) return true;
		return this.bodies.getChildren(sysId)?.has(groupParentId) ?? false;
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

	isInActiveSystem(parentId: string): boolean {
		return this.bodies.isInSystem(parentId, this.activeSystemId);
	}

	/** True if `body` (the body itself or by parentage) belongs to `sysId`. */
	isBodyInSystem(body: PositionedBody, sysId: string): boolean {
		return body.data.id === sysId || this.bodies.isInSystem(body.data.parentId, sysId);
	}

	/**
	 * True when focused somewhere in the Earth-Moon system (barycenter, Earth,
	 * Moon, an Earth satellite, or a lunar orbiter — setFocused resolves all of
	 * these to naif-3). Used to gate CelesTrak attribution, which is only
	 * relevant when Earth satellites are actually on screen.
	 */
	isFocusedOnEarthSystem(): boolean {
		return this.focusedSystemId === 'naif-3';
	}

	private isInFocusedSystem(parentId: string): boolean {
		return this.bodies.isInSystem(parentId, this.focusedSystemIdPlain);
	}

	/**
	 * Recomputes which moons qualify for FULL visibility, capped at MAX_FULL_MOONS.
	 * Among moons that pass the ratio threshold, only the closest to their parent (smallest a) win.
	 * Called every frame from updateCamera and on focus change from setFocused.
	 */
	private recomputeFullMoons(): void {
		this.fullMoonIds.clear();
		const sysId = this.focusedSystemIdPlain;
		if (!sysId) return;
		const camDistAU = this.cameraDistThreeJS / AU_SCALE;
		const children: PositionedBody[] = [];
		for (const id of this.bodies.getChildren(sysId) ?? []) {
			const b = this.bodies.bodiesById.get(id);
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
}
