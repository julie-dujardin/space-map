import {
	isAsteroid,
	ObjectType,
	sbdbOrbitClass,
	ZONE_A_RANGE,
	type PositionedBody
} from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { AU_SCALE } from '$lib/math/units';
import { BodyIndex, isTopLevelParent } from '$lib/scene/state/bodies.svelte';
import { EARTH_ID, SUN_ID } from '$lib/constants';
import { f64dist } from '$lib/scene/animation/math';
import type { ProbeStore } from '$lib/fetch/position/probes/store';
import { smallBodyCategory, type SmallBodyFilter } from '$lib/fetch/groups/registry';
import {
	VISIBILITY,
	REFERENCE_VIEWPORT_HEIGHT,
	PLANETARY_DISTANCE_RATIO_THRESHOLDS,
	SYSTEM_DISTANCE_RATIO_THRESHOLDS,
	FOCUSED_FULL_MULTIPLIER_MOON,
	FOCUSED_FULL_MULTIPLIER_SUN_ORBITING,
	MAX_FULL_MOONS,
	FOCUS_HIDE_MOON_MULTIPLIER,
	computeVisibilityFromRatio
} from '$lib/scene/visibility/thresholds';

const SMALL_BODY_ZONE_PREFIX = 'small_bodies/';

/** NAIF id of the Earth-Moon barycenter, returned by `containingSystemAt` for
 *  any probe inside the Earth system zone (Earth orbiters, lunar orbiters,
 *  mid-flyby probes). */
const EARTH_SYSTEM_NAIF = 3;

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
	/** True while the trajectory scrubber drives the focused system (see
	 *  {@link setTravelSystem}); cleared by any real focus. */
	private travelSystemActive = false;
	private cameraDistThreeJS = 0;
	private lastRecomputeDist = -1;
	/** Latest jd from `updateCamera`. Used by probe annotation lookups so
	 *  per-body callers don't have to thread jd through. */
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
		private readonly getProbeStore: () => ProbeStore | null = () => null,
		private readonly getEarthSatGroupFilter: () => ReadonlySet<string> | null = () => null,
		private readonly getSmallBodyFilter: () => SmallBodyFilter | null = () => null
	) {}

	/** Per-tick mask read by the orbit worker pool to hide non-matching small
	 *  bodies. Zero when the active filter is class-based (or none) — only the
	 *  flag-kind filter carries a non-zero mask. */
	getRequiredFlags(): number {
		const f = this.getSmallBodyFilter();
		return f?.kind === 'flag' ? f.mask : 0;
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
	updateCamera(dist: number, jd: number): void {
		this.cameraDistThreeJS = dist;
		this.currentJd = jd;
		this.moonVisibilityCache.clear();
		// Refresh focused-system from the live annotation when focused on a
		// probe — captured-at-setFocused state would go stale as jd advances
		// past the flyby window or as chunks settle after an async ensure().
		// While the trajectory scrubber owns the focus, the renderer drives the
		// system instead (setTravelSystem) and any prior probe focus is stale.
		if (!this.travelSystemActive) this.refreshProbeFocusedSystem();
		// Probes move between frames, so the hide threshold is recomputed every
		// frame (iterating direct children of one body is cheap).
		this.hideThresholdAU = this.computeHideThreshold();
		// Derived fresh each frame rather than on zoom edges: the focused system
		// can change while the zoom does not (flyby probe, scrubbed craft), and
		// edge-gating would hold the stale system active.
		this.isZoomedIn = dist / AU_SCALE < this.hideThresholdAU;
		this.activeSystemId = this.isZoomedIn ? this.focusedSystemIdPlain : null;
		// Only recompute when distance changes by more than 0.5% — avoids a filter+sort every frame
		if (Math.abs(dist - this.lastRecomputeDist) > this.lastRecomputeDist * 0.005 + 0.001) {
			this.lastRecomputeDist = dist;
			this.recomputeFullMoons();
		}
	}

	/** Probe focus reads the `systemIntervals` annotation instead of walking
	 *  parentId — a flyby probe's parentId flips per-frame and can be stale
	 *  during chunk-load gaps. No-op for non-probe focus. */
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

	/**
	 * The planetary system `body` belongs to (its barycenter's id), or null for
	 * top-level bodies, which are in no system.
	 */
	resolveSystemId(body: PositionedBody): string | null {
		// A planetary barycenter IS the system root (planets/moons are its children),
		// but the SSB (naif-0) is top-level, not a system.
		const isSystemBarycenter =
			body.data.objectType === ObjectType.BARYCENTER &&
			isTopLevelParent(body.data.parentId) &&
			!isTopLevelParent(body.data.id);
		const isTopLevel =
			body.data.objectType === ObjectType.STAR ||
			(!isSystemBarycenter && isTopLevelParent(body.data.parentId));
		if (isSystemBarycenter) return body.data.id;
		if (isTopLevel) return null;
		// parentId is either the system barycenter (e.g. Earth's parent is naif-3) or
		// a system member one level deeper (e.g. an Earth satellite's parent is naif-399,
		// whose parent is naif-3). Satellites aren't recorded as barycenter children
		// — too many — so resolve by walking up via bodiesById instead.
		const parent = this.bodies.bodiesById.get(body.data.parentId);
		return parent && !isTopLevelParent(parent.data.parentId)
			? parent.data.parentId
			: body.data.parentId;
	}

	/**
	 * Name the system the scrubbed trajectory craft is in — or null while it is
	 * in interplanetary space. The craft is nobody's child, so ordinary focus
	 * can't resolve its system; the renderer measures it against the trip's
	 * stops and drives this every frame, the way a flyby probe's annotation
	 * does. Holds until the next real focus.
	 *
	 * Naming only: whether the solar system actually hides stays with
	 * `updateCamera`'s zoom gate, same as for any other focus.
	 */
	setTravelSystem(sysId: string | null): void {
		this.travelSystemActive = true;
		if (sysId === this.focusedSystemIdPlain) return;
		this.focusedSystemId = sysId;
		this.focusedSystemIdPlain = sysId;
		this.lastRecomputeDist = -1; // force fullMoons recompute against the new system
	}

	clearTravelSystem(): void {
		this.travelSystemActive = false;
	}

	setFocused(body: PositionedBody): void {
		this.travelSystemActive = false;
		if (body.data.id === this.focusedBodyIdPlain) return;
		this.focusedBodyId = body.data.id;
		this.focusedBodyIdPlain = body.data.id;
		const sysId = this.resolveSystemId(body);
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

	/** Ratio-based visibility for a moon, gated on the focused system — the
	 *  distance ratio alone can't gate: camera-to-focus distance says nothing
	 *  about proximity to the parent, so an ungated moon pops in whenever the
	 *  camera zooms close to anything. An asteroid's "system" is the asteroid
	 *  itself: focusing one of its moons resolves focusedSystemId to it, but
	 *  focusing the asteroid leaves focusedSystemId null (top-level parent),
	 *  so match focusedBodyId too. Asteroid moons also skip the crowding cap
	 *  (sparse per parent). */
	getMoonVisibility(moon: PositionedBody): VISIBILITY {
		const cached = this.moonVisibilityCache.get(moon.data.id);
		if (cached !== undefined) return cached;
		let vis: VISIBILITY;
		// Asteroid parents live in `asteroidBodiesByZone`, not `bodiesById`, so go through getBody.
		const parent = this.bodies.getBody(moon.data.parentId);
		const isAsteroidMoon = parent !== undefined && isAsteroid(parent.data.objectType);
		let inFamily = this.isInFocusedSystem(moon.data.parentId);
		if (isAsteroidMoon && moon.data.parentId === this.focusedBodyIdPlain) inFamily = true;
		if (!inFamily) {
			vis = VISIBILITY.HIDE;
		} else if (isAsteroidMoon && !this.matchesSmallBodyClass(moon.data.parentId)) {
			// Asteroid moon inherits its parent's class — hide when the parent's
			// zone is filtered out.
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
			if (
				!isAsteroidMoon &&
				vis === VISIBILITY.FULL &&
				!this.fullMoonIds.has(moon.data.id) &&
				!isFocused
			)
				vis = VISIBILITY.CAPPED;
		}
		this.moonVisibilityCache.set(moon.data.id, vis);
		return vis;
	}

	/**
	 * Distance-ratio based visibility for non-moon, non-star bodies.
	 * Probes get moon-style ratio gating using instantaneous distance-to-parent
	 * as their characteristic length (no stable osculating `a`). Other planet-
	 * orbiting bodies (promoted Earth sats etc.) get moon-style ratio gating
	 * against their planet-relative `a`. Sun-orbiting asteroids/comets/planets
	 * use the solar-orbit semi-major axis ratio.
	 */
	getPlanetVisibility(body: PositionedBody, camDistThreeJS: number): VISIBILITY {
		// Check SPICE_PROBE before isSystemBody — Mars-zone probes carry parentId=naif-499,
		// which would otherwise satisfy isSystemBody and short-circuit to FULL.
		if (body.data.orbitalSource === OrbitalSource.SPICE_PROBE) {
			return this.getProbeVisibility(body);
		}

		// Earth-sat group focus: hide any earth-orbiting non-member, including
		// promoted ones (URL-loaded sats, labels-file auto-promotes) that don't
		// go through the chunk-time filter.
		const earthFilter = this.getEarthSatGroupFilter();
		if (earthFilter && body.data.parentId === EARTH_ID && !earthFilter.has(body.data.id)) {
			return VISIBILITY.HIDE;
		}

		// Small-body class focus: promoted asteroids/comets and dwarf planets
		// bypass the point-cloud render-time mask, so apply the zone check
		// here. Local hoist sidesteps a svelte `.svelte.ts` miscompile of
		// `(A || B) && C`.
		const ot = body.data.objectType;
		const isClassFiltered =
			isAsteroid(ot) || ot === ObjectType.COMET || ot === ObjectType.DWARF_PLANET;
		if (isClassFiltered && !this.matchesSmallBodyClass(body.data.id)) {
			return VISIBILITY.HIDE;
		}

		if (this.bodies.isSystemBody(body)) {
			if (!this.isInFocusedSystem(body.data.parentId)) return VISIBILITY.HIDE;
			const refA = body.data.a;
			if (!refA || refA <= 0) return VISIBILITY.FULL;
			const isFocused = body.data.id === this.focusedBodyIdPlain;
			return computeVisibilityFromRatio(
				camDistThreeJS / AU_SCALE / refA,
				this.scaledPlanetary,
				FOCUSED_FULL_MULTIPLIER_MOON,
				isFocused
			);
		}

		// Sun-orbiting: walk up to the barycenter to find solar-orbit semi-major axis.
		let refA = body.data.a;
		if (!isTopLevelParent(body.data.parentId)) {
			const parent = this.bodies.bodiesById.get(body.data.parentId);
			if (parent?.data.a) refA = parent.data.a;
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
		const isFocused = body.data.id === this.focusedBodyIdPlain;
		const tier = computeVisibilityFromRatio(
			camDistThreeJS / AU_SCALE / refA,
			this.scaledSystem,
			FOCUSED_FULL_MULTIPLIER_SUN_ORBITING,
			isFocused
		);
		// `refA` is the heliocentric orbit (Pluto borrows its barycenter's ~39 AU
		// a), so this ratio reaches CLOSE while a small body's disc is still
		// sub-pixel — dropping the halo with nothing to replace it. The disc-vs-halo
		// handoff belongs to applyLabelDisplay's pixel test; keep a halo here.
		return tier === VISIBILITY.CLOSE ? VISIBILITY.FULL : tier;
	}

	/** Probe visibility splits on whether the probe is captured. Flyby/cruise
	 *  (heliocentric fit present) → sun-orbiting style: ratio against distance to
	 *  the Sun with `scaledSystem` thresholds and no focused-system gate, so a
	 *  flyby stays visible in the solar view while transiting a planet's Hill
	 *  sphere. Captured (no heliocentric fit) → moon style: focused-system gate +
	 *  ratio against distance-to-parent (a stand-in for the missing osculating `a`). */
	private getProbeVisibility(body: PositionedBody): VISIBILITY {
		const ps = this.getProbeStore();
		const inSysNaif = ps ? ps.containingSystemAt(body.data.id, this.currentJd) : null;

		// Earth-sat group focus: clear the whole Earth system zone of probes
		// (Earth orbiters, lunar orbiters, mid-flyby) so they don't crowd the
		// focused group.
		if (inSysNaif === EARTH_SYSTEM_NAIF && this.getEarthSatGroupFilter()) {
			return VISIBILITY.HIDE;
		}

		const isFocused = body.data.id === this.focusedBodyIdPlain;

		// Flyby/cruise probes keep a heliocentric fit even mid-encounter; only a
		// captured orbiter is bound and takes the moon-style hidden-in-solar gate.
		const captured = ps ? !ps.hasHeliocentricFit(body.data.id, this.currentJd) : false;

		if (!captured) {
			const sun = this.bodies.bodiesById.get(SUN_ID);
			const helioDist = sun ? f64dist(body.position, sun.position) / AU_SCALE : 0;
			if (helioDist === 0) return VISIBILITY.FULL;
			const ratio = this.cameraDistThreeJS / AU_SCALE / helioDist;
			const tier = computeVisibilityFromRatio(
				ratio,
				this.scaledSystem,
				FOCUSED_FULL_MULTIPLIER_SUN_ORBITING,
				isFocused
			);
			// Probes are point-like — no mesh disc to take over from the icon, so the
			// CLOSE tier would hide the icon with nothing to replace it.
			return tier === VISIBILITY.CLOSE ? VISIBILITY.FULL : tier;
		}

		if (!this.isProbeInFocusedSystem(body)) return VISIBILITY.HIDE;
		const parent = this.bodies.bodiesById.get(body.data.parentId);
		if (!parent) return VISIBILITY.FULL;
		const distToParent = f64dist(body.position, parent.position) / AU_SCALE;
		if (distToParent === 0) return VISIBILITY.FULL;
		const ratio = this.cameraDistThreeJS / AU_SCALE / distToParent;
		const fullThreshold =
			this.scaledPlanetary[VISIBILITY.FULL] * (isFocused ? FOCUSED_FULL_MULTIPLIER_MOON : 1);
		return ratio <= fullThreshold ? VISIBILITY.FULL : VISIBILITY.HIDE;
	}

	/** True when the probe is in the focused planetary system. Checks `parentId`
	 *  first, then falls back to the `systemIntervals` annotation so flyby probes
	 *  whose parent hasn't flipped yet still count as in-system. */
	private isProbeInFocusedSystem(body: PositionedBody): boolean {
		const parentId = body.data.parentId;
		if (!isTopLevelParent(parentId) && this.isInFocusedSystem(parentId)) return true;
		const ps = this.getProbeStore();
		if (!ps) return false;
		const sysNaif = ps.containingSystemAt(body.data.id, this.currentJd);
		return sysNaif !== null && this.isInFocusedSystem(`naif-${sysNaif}`);
	}

	/** Full rendering = halo + trail. Suppressed for out-of-system bodies when zoomed in.
	 *  Probes also pass via the `systemIntervals` annotation, so a flyby probe stays
	 *  visible even when its parentId hasn't flipped yet (chunk-load gap). */
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
	 * A `class` small-body filter hides non-matching `small_bodies/<class>`
	 * zones at render time; a `flag` filter (NEO/PHA) leaves every zone visible
	 * and lets the orbit worker mask non-matching points via `requiredFlags`.
	 */
	isAsteroidGroupVisible(zone: string): boolean {
		if (this.activeSystemId) return false;
		const filter = this.getSmallBodyFilter();
		if (filter && zone.startsWith(SMALL_BODY_ZONE_PREFIX)) {
			const className = zone.slice(SMALL_BODY_ZONE_PREFIX.length);
			if (filter.kind === 'class' && className !== filter.className) return false;
			if (filter.kind === 'category' && smallBodyCategory(className) !== filter.category) {
				return false;
			}
		}
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

	/** Dump every visibility signal for one body id (test + console diagnostic). */
	debugBody(id: string): Record<string, unknown> | null {
		const body = this.bodies.getBody(id);
		if (!body) return { id, found: false };
		const ot = body.data.objectType;
		const isMoon = ot === ObjectType.MOON;
		const ps = this.getProbeStore();
		const vis = isMoon
			? this.getMoonVisibility(body)
			: this.getPlanetVisibility(body, this.cameraDistThreeJS);
		return {
			id,
			name: body.data.name,
			objectType: ObjectType[ot],
			orbitalSource: body.data.orbitalSource,
			parentId: body.data.parentId,
			a: body.data.a,
			jd: this.currentJd,
			isMoon,
			isSystemBody: this.bodies.isSystemBody(body),
			isInFocusedSystem_parent: this.isInFocusedSystem(body.data.parentId),
			focusedBodyId: this.focusedBodyIdPlain,
			focusedSystemId: this.focusedSystemIdPlain,
			activeSystemId: this.activeSystemId,
			isZoomedIn: this.isZoomedIn,
			hideThresholdAU: this.hideThresholdAU,
			containingSystemAt: ps ? ps.containingSystemAt(body.data.id, this.currentJd) : null,
			camDistAU: this.cameraDistThreeJS / AU_SCALE,
			visibility: VISIBILITY[vis],
			hasFullRendering: this.hasFullRendering(body)
		};
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

	/** True when no small-body filter is active or the body satisfies it.
	 *  Unresolved bodies don't match, so off-class promoted bodies stay hidden.
	 *  Asteroid moons are gated via parent-id lookup in getMoonVisibility. */
	private matchesSmallBodyClass(id: string): boolean {
		const filter = this.getSmallBodyFilter();
		if (filter === null) return true;
		if (filter.kind === 'class' || filter.kind === 'category') {
			const className = this.resolveSmallBodyClass(id);
			if (className === null) return false;
			return filter.kind === 'class'
				? className === filter.className
				: smallBodyCategory(className) === filter.category;
		}
		// Promoted small bodies live in `asteroidBodiesByZone`, not
		// `bodiesById` — go through getBody so flags resolve.
		const body = this.bodies.getBody(id);
		if (body === undefined) return false;
		return ((body.data.flags ?? 0) & filter.mask) === filter.mask;
	}

	/** SBDB orbit-class name for a small body: its zone suffix, or — for
	 *  un-zoned dwarf planets — derived from heliocentric (a, e) since AMO/MCA/APO
	 *  overlap the main belt's `a` band. Walks one level up for Pluto, whose
	 *  `data.a` is around its barycenter. Null when the class can't be resolved. */
	private resolveSmallBodyClass(id: string): string | null {
		const zone = this.bodies.findAsteroidZone(id);
		if (zone && zone.startsWith(SMALL_BODY_ZONE_PREFIX)) {
			return zone.slice(SMALL_BODY_ZONE_PREFIX.length);
		}
		const body = this.bodies.bodiesById.get(id);
		if (body?.data.objectType !== ObjectType.DWARF_PLANET) return null;
		let a = body.data.a;
		let e = body.data.e;
		if (!isTopLevelParent(body.data.parentId)) {
			const parent = this.bodies.bodiesById.get(body.data.parentId);
			if (parent?.data.a) {
				a = parent.data.a;
				e = parent.data.e;
			}
		}
		return sbdbOrbitClass(a, e);
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

	/** Camera distance (AU) below which the solar system is decluttered.
	 *  Infinity when no system is focused — nothing to declutter for. */
	private computeHideThreshold(): number {
		const sysId = this.focusedSystemIdPlain;
		if (!sysId) return Infinity;
		return this.systemReachAU(sysId);
	}

	/**
	 * How far `sysId` reaches, AU — the declutter radius, and what the scrubbed
	 * trajectory craft measures itself against. Walks direct children of the
	 * system root and direct children of its planet (e.g. naif-399 under
	 * naif-3), summing in moons (2×a) and spacecraft (instantaneous distance to
	 * parent). Returns 0 when no satellite qualifies — solar system never hides.
	 */
	systemReachAU(sysId: string): number {
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
					// Skip flyby probes (loadParentId mismatches the current parentId
					// flipped by the per-frame propagator) — their distance can reach
					// 2× Hill and would spike the threshold past the encounter.
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
