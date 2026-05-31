import { ObjectType, ZONE_A_RANGE, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { AU_SCALE } from '$lib/math/units';
import { BodyIndex, isTopLevelParent } from '$lib/scene/state/bodies.svelte';
import { SUN_ID } from '$lib/constants';
import { f64dist } from '$lib/scene/animation/math';
import type { ProbeStore } from '$lib/fetch/position/probes/store';
import {
	VISIBILITY,
	REFERENCE_VIEWPORT_HEIGHT,
	PLANETARY_DISTANCE_RATIO_THRESHOLDS,
	SYSTEM_DISTANCE_RATIO_THRESHOLDS,
	FOCUSED_FULL_MULTIPLIER_MOON,
	FOCUSED_FULL_MULTIPLIER_SPACECRAFT,
	MAX_FULL_MOONS,
	FOCUS_HIDE_MOON_MULTIPLIER,
	computeVisibilityFromRatio
} from '$lib/scene/visibility/thresholds';

/**
 * Owns focus state and turns camera distance + focus into per-body visibility
 * decisions. Reads body topology from {@link BodyIndex}. Plain mirrors of the
 * reactive fields exist because every `$state` getter trips a reactive-source
 * tag in dev mode, dominating the per-body hot loop.
 */
export class VisibilityController {
	/** Reactive — Svelte consumers read this (attribution bar, popover). */
	focusedBodyId = $state<string>(SUN_ID);
	focusedSystemId = $state<string | null>(null);
	/** Set only when zoomed in — drives hiding of other systems. */
	activeSystemId: string | null = null;
	isZoomedIn = false;

	private focusedBodyIdPlain: string = SUN_ID;
	private focusedSystemIdPlain: string | null = null;
	private cameraDistThreeJS = 0;
	private lastRecomputeDist = -1;
	/** Latest jd from `updateCamera` — used by probe annotation lookups so the
	 *  focused-system + visibility re-derivations always see the current time
	 *  without each caller having to thread jd through.  */
	private currentJd = 0;
	/**
	 * Camera distance (AU) below which the solar system hides so the focused
	 * planetary system stands out. Computed from the focused body's satellites:
	 * 2×a for moons, instantaneous distance-to-parent for spacecraft (probes in
	 * eccentric orbits don't carry a stable a). Zero when the focused body has
	 * no qualifying satellites — solar system never hides in that case.
	 */
	private hideThresholdAU = 0;
	// Cached scaled thresholds — recomputed in updateViewport() on canvas resize.
	private scaledPlanetary = PLANETARY_DISTANCE_RATIO_THRESHOLDS;
	private scaledSystem = SYSTEM_DISTANCE_RATIO_THRESHOLDS;
	/** IDs of moons allowed FULL visibility after the crowding cap is applied. */
	private fullMoonIds = new Set<string>();
	/** Per-frame cache for getMoonVisibility, cleared in updateCamera. */
	private moonVisibilityCache = new Map<string, VISIBILITY>();

	constructor(
		private readonly bodies: BodyIndex,
		private readonly getProbeStore: () => ProbeStore | null = () => null
	) {}

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
	updateCamera(dist: number, jd: number): void {
		this.cameraDistThreeJS = dist;
		this.currentJd = jd;
		this.moonVisibilityCache.clear();
		// Probe focus: when the focused body is a probe, re-derive
		// `focusedSystemId` from its writer-stamped annotation every frame —
		// captured-at-setFocused state would go stale as jd advances past
		// the flyby window (or as chunks load after a transient parentId
		// flip during async ensure()). Cheap: one chunk lookup + interval
		// scan against the focused id.
		this.refreshProbeFocusedSystem();
		// Probes move between frames, so the hide threshold is recomputed every
		// frame (iterating direct children of one body is cheap).
		this.hideThresholdAU = this.computeHideThreshold();
		const zoomed = dist / AU_SCALE < this.hideThresholdAU;
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

	/** Probe focus uses the writer-stamped `systemIntervals` annotation rather
	 *  than the parentId-walk used for everything else: parentId on a flyby
	 *  probe flips per-frame and can transiently disagree with the probe's
	 *  actual system membership during chunk-load gaps. Falls back to the
	 *  parentId-derived value when the focused body isn't a probe or no
	 *  annotation is available. */
	private refreshProbeFocusedSystem(): void {
		const ps = this.getProbeStore();
		if (!ps) return;
		const focused = this.bodies.bodiesById.get(this.focusedBodyIdPlain);
		if (!focused || focused.data.orbitalSource !== OrbitalSource.SPICE_PROBE) return;
		const sysNaif = ps.containingSystemAt(focused.data.id, this.currentJd);
		const sysId = sysNaif !== null ? `naif-${sysNaif}` : null;
		if (sysId === this.focusedSystemIdPlain) return;
		this.focusedSystemId = sysId;
		this.focusedSystemIdPlain = sysId;
		this.lastRecomputeDist = -1; // force fullMoons recompute against the new system
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
		// Refresh the hide threshold against the new focus before deciding
		// whether the existing camera distance counts as "zoomed in".
		this.hideThresholdAU = this.computeHideThreshold();
		this.isZoomedIn = this.cameraDistThreeJS / AU_SCALE < this.hideThresholdAU;
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
			// e < 0.9 → not a comet, so a zero/missing a is a data problem worth surfacing.
			if (refA === 0 && body.data.e < 0.9) {
				console.warn(
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

	/** Full rendering = halo + trail. Suppressed for out-of-system bodies when zoomed in.
	 *  For probes, also consults the writer-stamped `systemIntervals` annotation —
	 *  a flyby probe shows up as inside the active system even if its parentId hasn't
	 *  flipped yet (chunk-load gap before the per-frame propagator re-resolves the
	 *  preferred zone). */
	hasFullRendering(body: PositionedBody): boolean {
		const sysId = this.activeSystemId;
		if (!sysId) return true;
		if (
			this.isInActiveSystem(
				isTopLevelParent(body.data.parentId) ? body.data.id : body.data.parentId
			)
		)
			return true;
		if (body.data.orbitalSource !== OrbitalSource.SPICE_PROBE) return false;
		const ps = this.getProbeStore();
		if (!ps) return false;
		const sysNaif = ps.containingSystemAt(body.data.id, this.currentJd);
		return sysNaif !== null && this.isInActiveSystem(`naif-${sysNaif}`);
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

	/**
	 * Camera distance (AU) below which the solar system is decluttered. Walks
	 * direct children of the focused system root and direct children of the
	 * focused planet (e.g. naif-399 under naif-3), summing in moons (2×a) and
	 * spacecraft (instantaneous distance to parent). Returns 0 when no
	 * satellite qualifies — solar system never hides.
	 */
	private computeHideThreshold(): number {
		const sysId = this.focusedSystemIdPlain;
		if (!sysId) return Infinity;
		let max = 0;
		const visit = (parentId: string, recurse: boolean): void => {
			const childIds = this.bodies.getChildren(parentId);
			if (!childIds) return;
			for (const id of childIds) {
				const child = this.bodies.bodiesById.get(id);
				if (!child) continue;
				const ot = child.data.objectType;
				if (ot === ObjectType.MOON) {
					const v = FOCUS_HIDE_MOON_MULTIPLIER * child.data.a;
					if (v > max) max = v;
				} else if (ot === ObjectType.SPACECRAFT) {
					// Flyby probes have parentId flipped by the per-frame propagator
					// (heliocentric → planet during Mars gravity assist); their
					// distance to the planet can reach 2× Hill, which would spike
					// the threshold and keep the system "active" past the encounter.
					// Skip them — only stable members (captured orbiters, moons)
					// should set the system's scale.
					const lp = child.data.loadParentId;
					if (lp && lp !== child.data.parentId) continue;
					const parent = this.bodies.bodiesById.get(child.data.parentId);
					if (!parent) continue;
					const v = f64dist(child.position, parent.position) / AU_SCALE;
					if (v > max) max = v;
				} else if (recurse && (ot === ObjectType.PLANET || ot === ObjectType.DWARF_PLANET)) {
					// Spacecraft typically parent on the planet itself (naif-X99),
					// not the system barycenter — walk one extra level so LEO/GEO
					// sats and similar planet-orbiters are picked up.
					visit(child.data.id, false);
				}
			}
		};
		visit(sysId, true);
		return max;
	}
}
