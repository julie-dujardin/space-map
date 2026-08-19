<!--
  The travel panel: describe a trip, get trajectories.

  Two steps. The first describes the trip and lists what could fly it, with all
  those trajectories drawn on the map at once. Choosing one replaces the form
  with that trajectory in detail, and the map with that arc and its timeline.
  `panel.selectedRoute` is which step is showing.

  The whole trip is a link: its two ends are the path (`/nav/<from>/<to>`) and
  everything else — when to go, what to fly, which trajectory is read — is the
  query. The panel owns the live state and mirrors it out; the URL is how it
  comes back.
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import ArrowUpDownIcon from '@lucide/svelte/icons/arrow-up-down';
	import CircleAlertIcon from '@lucide/svelte/icons/circle-alert';
	import MoveRightIcon from '@lucide/svelte/icons/move-right';
	import type { BodyData } from '$lib/types/objects';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { formatJulianDate } from '$lib/format/date';
	import {
		arrivalCost,
		buildTrajectoryPath,
		canDepartFrom,
		checkFeasibility,
		departureCost,
		hohmannArcDays,
		nextTransferWindows,
		orbitChangeEnds,
		SAME_RADIUS_KM,
		systemArcBounds,
		transferScale,
		travelConstants,
		type AeroAssist,
		type EphemerisSamples,
		type Route,
		type TrajectoryFrame,
		type TrajectoryPath,
		type TravelBody
	} from '$lib/math/travel';
	import {
		aeroPressurePa,
		lookupIn,
		toTravelBody,
		transferCenterId,
		transferFrame,
		transferPlan,
		type TransferPlan
	} from '$lib/travel/travel-body';
	import {
		solveRequestKey,
		TravelPanelState,
		type BlockReason,
		type SolveRequest
	} from '$lib/travel/panel.svelte';
	import { ASSIST_BODY_IDS } from '$lib/travel/assist-bodies';
	import {
		ORIGIN_MODES,
		serializeTripSuffix,
		type EndpointMode,
		type RouteOption,
		type TimeMode,
		type TripState
	} from '$lib/travel/trip';
	import type { EndSite, TravelEndpointPick } from '$lib/travel/endpoint';
	import type { LaunchPad } from '$lib/travel/launch-pad';
	import { surfaceSiteAt } from '$lib/travel/surface-site';
	import { fetchBodyNomenclature } from '$lib/fetch/nomenclature/fetch';
	import {
		hasGround,
		maxCustomAltitudeKm,
		orbitChoices,
		orbitFacts,
		type OrbitChoice
	} from '$lib/travel/orbits';
	import { activeFamily, familyOf, routeTabs, type RouteFamily } from '$lib/travel/route-families';
	import { buildTimeline, type DrawnDates, type TimelineEntry } from '$lib/travel/timeline';
	import { routeHazards, type Hazard } from '$lib/travel/hazards';
	import type { LabelledPath } from '$lib/travel/labelled-path';
	import { formatAcceleration } from '$lib/travel/format';
	import { Button } from '$lib/components/ui/button/index.js';
	import InlineMenu from './InlineMenu.svelte';
	import VehicleField from './VehicleField.svelte';
	import TimingField from './TimingField.svelte';
	import ManifestField from './ManifestField.svelte';
	import EndpointField from './EndpointField.svelte';
	import RouteList from './RouteList.svelte';
	import CruiseBox from './CruiseBox.svelte';
	import RouteTabs from './RouteTabs.svelte';
	import RouteDetail from './RouteDetail.svelte';
	import { endpointModeLabel, groundLabel } from './endpoint-labels';
	import { hazardKey, routeKey, timelineKey } from './route-keys';

	interface Props {
		/** Whether the panel is in the phone layout. Its pickers take the whole
		 *  screen there rather than opening a popover over a drawer's width. */
		isMobile?: boolean;
		/** Where the trip starts; null until one is chosen. */
		origin: BodyData | null;
		/** Where it ends; null until one is chosen. */
		target: BodyData | null;
		/** Localized labels for the two ends. */
		originName: string | null;
		targetName: string | null;
		/** Where on its body an end sits, when it sits somewhere: a named feature,
		 *  or a probe parked on the surface. */
		originSite: EndSite | null;
		targetSite: EndSite | null;
		/** The pads an end standing on a launch range could stand on instead,
		 *  busiest first, and which one it stands on now. Empty for every other
		 *  kind of end. */
		originPads?: readonly LaunchPad[];
		targetPads?: readonly LaunchPad[];
		originPadCode?: string | null;
		targetPadCode?: string | null;
		onOriginPadPick?: (pad: LaunchPad) => void;
		onTargetPadPick?: (pad: LaunchPad) => void;
		/** Whether the URL names each end at all. Tells the two silences apart:
		 *  nothing chosen yet, versus somewhere with no orbit to meet. */
		originPicked: boolean;
		targetPicked: boolean;
		/** The two ends and their chains up to the Sun, for resolving primaries. */
		bodiesById: Map<string, BodyData>;
		/** Now, on the app's clock, as a Julian Date. */
		nowJd: number;
		/** Bodies each end may not be — the other end, plus anything the kernel
		 *  cannot solve a transfer against it. */
		excludeForOrigin: ReadonlySet<string>;
		excludeForTarget: ReadonlySet<string>;
		/** Detail bundles for the two ends; null until they land. Only the
		 *  atmosphere is read, so a route just prices airless until then. */
		originDetail?: GlobalObjectData | null;
		targetDetail?: GlobalObjectData | null;
		/** The trip's terms as the URL has them — what the panel opens on, and what
		 *  browser-back restores it to. */
		trip: TripState;
		/**
		 * Which frame the trip's ends are drawn in. The map's control owns it — it
		 * changes the picture, not the trip. Only the plan is drawn in it: an
		 * alternative is a shape rather than an itinerary, and the hazard scan reads
		 * distances from the Sun, the one frame they mean anything in.
		 */
		viewFrame: TrajectoryFrame;
		/** Move either end. The URL owns them, so the panel asks. */
		onOriginChange: (pick: TravelEndpointPick) => void;
		onTargetChange: (pick: TravelEndpointPick) => void;
		/** Exchange the two ends. */
		onSwap: () => void;
		/** Hand the terms back out after any change, for the URL to mirror. */
		onTripChange: (trip: TripState) => void;
		/** The trajectory being read, as geometry with a label for each of its ends,
		 *  for the map to draw. Null whenever there is nothing to show. */
		onPathChange: (plan: LabelledPath | null) => void;
		/** Every trajectory still on offer, as geometry with a label for each of its
		 *  ends — what the map shows while the choice between them is open, and how
		 *  one is taken off the map. Empty once one has been chosen. */
		onOptionsChange: (options: readonly LabelledPath[]) => void;
		/** Which trajectory the reader is pointing at, by whichever end of the link
		 *  they touched. Null when none. */
		onHoverChange: (id: string | null) => void;
		/** The same trajectory as the legs it is made of, for the timeline along the
		 *  bottom of the map. */
		onTimelineChange: (entries: TimelineEntry[] | null) => void;
		/** What the trajectory being read puts the craft through, for the map to band
		 *  its arc with. Trajectory only — the craft's own reading of them stays in
		 *  the detail. */
		onHazardsChange: (hazards: readonly Hazard[]) => void;
		/** What a body passed on the way is called. The two ends name themselves;
		 *  this is for the ones in between — the body a swing-by goes past. */
		resolveBodyName: (bodyId: string) => string;
		/** An end as it is described at a date the search reached, when the row in
		 *  hand does not describe it there. See `RefineEnd`. */
		refineBody?: (id: string, jd: number) => Promise<BodyData | null>;
		/** Where an end really is over the dates a trip can reach, for the ends no
		 *  conic about their primary describes. See `EphemerisSamples`. */
		sampleEnd?: (id: string, centerId: string) => Promise<EphemerisSamples | null>;
	}
	let {
		isMobile = false,
		origin,
		target,
		originName,
		targetName,
		originSite,
		targetSite,
		originPads = [],
		targetPads = [],
		originPadCode = null,
		targetPadCode = null,
		onOriginPadPick,
		onTargetPadPick,
		originPicked,
		targetPicked,
		bodiesById,
		nowJd,
		excludeForOrigin,
		excludeForTarget,
		originDetail = null,
		targetDetail = null,
		trip,
		viewFrame,
		onOriginChange,
		onTargetChange,
		onSwap,
		onTripChange,
		onPathChange,
		onOptionsChange,
		onHoverChange,
		onTimelineChange,
		onHazardsChange,
		resolveBodyName,
		refineBody,
		sampleEnd
	}: Props = $props();

	// Seeded once; from here on the two are kept in step by the effects below.
	const panel = new TravelPanelState(untrack(() => trip));

	/** One empty list, shared. A fresh `[]` per read would make every consumer of
	 *  "no hazards" look like a change and re-run on the clock. */
	const NO_HAZARDS: readonly Hazard[] = [];

	// The panel holds the live trip and the URL mirrors it; back/forward is the
	// one direction that flows the other way. Both sides compare the serialized
	// form, so a write that changes nothing the URL carries — a date under "leave
	// now" — cannot come back as a change and start the two echoing.
	$effect(() => {
		const next = panel.trip;
		untrack(() => onTripChange(next));
	});
	$effect(() => {
		const incoming = trip;
		untrack(() => {
			if (serializeTripSuffix(incoming) !== serializeTripSuffix(panel.trip)) {
				panel.applyTrip(incoming);
			}
		});
	});
	let openField = $state<'origin' | 'target' | 'craft' | null>(null);

	/**
	 * Only one box is open at a time, and the one closing may not be the one that
	 * just opened: clicking the other box opens it and *then* tells this one it
	 * closed, so an unguarded assignment shuts the box the click was for.
	 */
	function setOpenField(field: 'origin' | 'target' | 'craft', open: boolean) {
		if (open) openField = field;
		else if (openField === field) openField = null;
	}
	// Whether each end is a place rather than a whole body; the panel state mirrors
	// it so the mode getters and the field's own rendering agree.
	$effect(() => {
		panel.originAtSite = originSite !== null;
		panel.targetAtSite = targetSite !== null;
	});

	// Where each end sits on its globe, so the drawn trajectory can reach the spot
	// rather than the body. A probe or a pad brings its own coordinates; a feature
	// is named and has to be looked up, so it arrives late like the names do and
	// the geometry key carries it.
	let originSitePlace = $state<{ lat: number; lon: number } | null>(null);
	let targetSitePlace = $state<{ lat: number; lon: number } | null>(null);
	function loadSitePlace(
		bodyId: string | undefined,
		site: EndSite | null,
		set: (place: { lat: number; lon: number } | null) => void,
		still: () => boolean
	) {
		set(null);
		if (!bodyId || !site) return;
		if (site.kind === 'point') {
			set({ lat: site.latDeg, lon: site.lonDeg });
			return;
		}
		const featureId = site.featureId;
		fetchBodyNomenclature(bodyId)
			.then((features) => {
				const found = features.find((f) => f.featureId === featureId);
				if (found && still()) set({ lat: found.lat, lon: found.lon });
			})
			.catch((e) => console.warn(`[travel] could not place feature ${featureId} on ${bodyId}:`, e));
	}
	$effect(() => {
		const bodyId = origin?.id;
		const site = originSite;
		untrack(() =>
			loadSitePlace(
				bodyId,
				site,
				(place) => (originSitePlace = place),
				() => origin?.id === bodyId && originSite === site
			)
		);
	});
	$effect(() => {
		const bodyId = target?.id;
		const site = targetSite;
		untrack(() =>
			loadSitePlace(
				bodyId,
				site,
				(place) => (targetSitePlace = place),
				() => target?.id === bodyId && targetSite === site
			)
		);
	});
	// The same coordinates price the trip: where a launch leaves from decides how
	// much of the body's spin it keeps, and a landing pays the same in reverse.
	$effect(() => {
		panel.originSiteLatDeg = originSitePlace?.lat ?? null;
		panel.targetSiteLatDeg = targetSitePlace?.lat ?? null;
	});

	let originSiteAt = $derived(
		origin && originSitePlace
			? surfaceSiteAt(origin, originDetail, originSitePlace.lat, originSitePlace.lon)
			: null
	);
	let targetSiteAt = $derived(
		target && targetSitePlace
			? surfaceSiteAt(target, targetDetail, targetSitePlace.lat, targetSitePlace.lon)
			: null
	);

	// The trajectory under the pointer, wherever the pointer is: its mark on the
	// launch-window field, or one of its labels out on the map. Both write here and
	// both read it back, which is what makes the two pictures one.
	let hoveredProfile = $state<string | null>(null);
	$effect(() => {
		const id = hoveredProfile;
		untrack(() => onHoverChange(id));
	});
	$effect(() => () => onHoverChange(null));

	// A link can name a craft, and the picker is where the catalogue would
	// otherwise be fetched — without this the trip reads as having no craft until
	// someone opens a list they have no reason to open.
	$effect(() => {
		if (panel.vehicleId !== null && panel.vehicles.length === 0) void panel.loadVehicles();
	});

	// Only craft the trip could actually be flown with: able to leave the way it
	// does, and — once a trajectory is being read — not priced out of it on Δv
	// or endurance. A refusal to judge is not a no, so the unjudgeable stay. The
	// chosen craft stays whatever it can do: hiding a selection would read as
	// losing it.
	let shownVehicles = $derived.by(() => {
		const route = panel.selectedRoute;
		return panel.vehicles.filter((vehicle) => {
			if (vehicle.id === panel.vehicleId) return true;
			if (!canDepartFrom(vehicle, panel.departureMode)) return false;
			if (!route) return true;
			const fit = checkFeasibility(vehicle, route, panel.manifest);
			if (fit.status === 'insufficient-dv' || fit.status === 'over-c3') return false;
			return fit.enduranceRatio === undefined;
		});
	});

	// What kind of transfer this pair needs — across the solar system, out to a
	// body's own moon, or between two moons of one planet — and so which orbit
	// each end is described by and what the arc goes round.
	let lookup = $derived(lookupIn(bodiesById));
	let plan = $derived<TransferPlan | null>(
		origin && target ? transferPlan(origin, target, lookup) : null
	);
	let frame = $derived(transferFrame(plan));

	/**
	 * Which end a same-system transfer crosses to, when that end is measured
	 * rather than modelled — a satellite whose conic about its primary is a
	 * fiction, like anything held at a Lagrange point, has to be read off its own
	 * positions. A key rather than the pair itself: the bodies come off a map
	 * replaced as the catalogue streams in, and a fresh object every time would
	 * re-read a hundred positions for an unchanged trip.
	 */
	let measuredKey = $derived.by(() => {
		const primary = frame.systemPrimary;
		if (!primary) return null;
		const satellite = primary === 'departure' ? target : origin;
		const centre = primary === 'departure' ? origin : target;
		if (!satellite?.id.startsWith('probe-') || !centre) return null;
		return `${satellite.id}|${centre.id}`;
	});

	// Landing after the first solve, the way the names and the site coordinates
	// do: the search runs against the elements and re-runs once these are in.
	let samples = $state.raw<{ forId: string; samples: EphemerisSamples } | null>(null);
	$effect(() => {
		const key = measuredKey;
		let stale = false;
		samples = null;
		if (key === null || !sampleEnd) return;
		const [id, centerId] = key.split('|');
		void sampleEnd(id, centerId).then((found) => {
			if (!stale && found) samples = { forId: id, samples: found };
		});
		return () => (stale = true);
	});

	/** The measured positions, once they are for the body being asked about. */
	function measured(body: TravelBody | null): TravelBody | null {
		if (!body || samples?.forId !== body.id) return body;
		return { ...body, samples: samples.samples };
	}

	// The kernel's view of each end, rebuilt whenever either body or its detail
	// changes.
	let originTravel = $derived<TravelBody | null>(
		measured(origin ? toTravelBody(origin, lookup, originDetail, frame.orbit) : null)
	);
	let targetTravel = $derived<TravelBody | null>(
		measured(target ? toTravelBody(target, lookup, targetDetail, frame.orbit) : null)
	);

	// The same two ends the routes were priced against. A body that does not
	// keep still is re-described at the trip's own dates, so anything read back
	// off a route has to ask the same body — drawing against the ends as they
	// stand now put a system transfer's satellite out of its own cruise reach.
	let solved = $derived(panel.pricedEnds);
	let pathOrigin = $derived(solved?.origin ?? originTravel);
	let pathTarget = $derived(solved?.target ?? targetTravel);

	// Only a body with a surface can be landed on or left from the ground.
	let originHasGround = $derived(originTravel ? hasGround(originTravel) : true);
	let targetHasGround = $derived(targetTravel ? hasGround(targetTravel) : true);

	// What each body contributes to which orbits it can hold: its spin, from the
	// detail bundle, and how much room it has, from the orbit it is itself on.
	let originFacts = $derived(
		origin && originTravel ? orbitFacts(origin, originTravel, originDetail, lookup) : null
	);
	let targetFacts = $derived(
		target && targetTravel ? orbitFacts(target, targetTravel, targetDetail, lookup) : null
	);
	// A named place on a surface has already answered how it is met, so its box
	// offers nothing — which is what an empty list means to `EndpointField`.
	let originChoices = $derived<OrbitChoice[]>(
		originTravel && originFacts && !panel.originAtSite
			? orbitChoices(originTravel, originFacts, 'origin', {
					hasSurface: originHasGround,
					customAltKm: panel.originAltKm,
					customApoAltKm: panel.originApoAltKm,
					incDeg: panel.originIncDeg
				})
			: []
	);
	let targetChoices = $derived.by<OrbitChoice[]>(() => {
		const all =
			targetTravel && targetFacts && !panel.targetAtSite
				? orbitChoices(targetTravel, targetFacts, 'target', {
						hasSurface: targetHasGround,
						customAltKm: panel.targetAltKm,
						customApoAltKm: panel.targetApoAltKm,
						incDeg: panel.targetIncDeg
					})
				: [];
		// Where the trip already is is not somewhere to go: on a same-body trip the
		// departure's own orbit drops out of the arrivals, along with the two that
		// mean nothing at home — flying past where you are, and landing back on the
		// ground you lifted off.
		if (!frame.orbitChange) return all;
		const from = panel.originOrbit;
		return all.filter((choice) => {
			if (choice.kind === 'flyby') return false;
			if (choice.kind === 'surface') return panel.departureMode !== 'surface';
			if (!from || !choice.orbit) return true;
			return (
				Math.abs(choice.orbit.rPeriKm - from.rPeriKm) > SAME_RADIUS_KM ||
				Math.abs(choice.orbit.rApoKm - from.rApoKm) > SAME_RADIUS_KM
			);
		});
	});

	/**
	 * A mode the body cannot hold is not a mode: a link naming a stationary orbit
	 * at Venus falls back to the low one rather than pricing a trip it cannot fly.
	 *
	 * Guarded on the detail bundle having landed. The spin that says whether a
	 * stationary orbit exists arrives with that bundle, so during the wait every
	 * named orbit is missing — an unguarded check would read that as "no
	 * geostationary orbit" and rewrite a shared link's mode on the way in.
	 */
	$effect(() => {
		if (!originDetail || !originChoices.length) return;
		if (!originChoices.some((c) => c.kind === panel.originMode)) panel.originMode = 'low-orbit';
	});
	$effect(() => {
		if (!targetDetail || !targetChoices.length) return;
		if (targetChoices.some((c) => c.kind === panel.targetMode)) return;
		// The low orbit wherever it is offered, and otherwise whatever is — on a
		// same-body trip the low orbit is sometimes the end the craft is already at.
		panel.targetMode =
			targetChoices.find((c) => c.kind === 'low-orbit')?.kind ?? targetChoices[0].kind;
	});

	/** Which pad each end stands on, when it stands on one — the row the box
	 *  shows as pressed, and the line under the body's name. */
	let originPad = $derived(originPads.find((p) => p.code === originPadCode) ?? null);
	let targetPad = $derived(targetPads.find((p) => p.code === targetPadCode) ?? null);
	let originGroundLine = $derived(groundLabel('origin', originPad, originSitePlace));
	let targetGroundLine = $derived(groundLabel('target', targetPad, targetSitePlace));

	/** Null if there was no choice: a named place, or a body with no data. */
	function endLabel(
		role: 'origin' | 'target',
		isFeature: boolean,
		mode: EndpointMode,
		choices: OrbitChoice[]
	): string | null {
		// A place answered "how" by being where it is. The trajectory line names
		// the place and stops there — which pad of a range, or which corner of a
		// crater, is the picker's business and would treble the line's height.
		if (isFeature || choices.length === 0) return null;
		// Use the priced shape. A body has a maximum orbit height, and both ends of
		// a custom orbit come off it.
		const priced = choices.find((c) => c.kind === mode);
		return endpointModeLabel(mode, role, priced?.periAltKm ?? null, priced?.apoAltKm ?? null);
	}
	let originModeLabel = $derived(
		endLabel('origin', panel.originAtSite, panel.originMode, originChoices)
	);
	let targetModeLabel = $derived(
		endLabel('target', panel.targetAtSite, panel.targetMode, targetChoices)
	);

	// The orbit each end is met in, handed to the panel so every builder prices
	// the same one. A mode with no orbit of its own — a landing, a flyby — leaves
	// it unset and the kernel falls back to its parking orbit.
	$effect(() => {
		panel.setEndOrbit('origin', originChoices.find((c) => c.kind === panel.originMode)?.orbit);
	});
	$effect(() => {
		panel.setEndOrbit('target', targetChoices.find((c) => c.kind === panel.targetMode)?.orbit);
	});

	/**
	 * What each orbit would cost at this end, on the trajectory being read.
	 * Priced from the chosen route's excess speed, so the figures move with the
	 * trajectory rather than standing for a trip nobody picked — and there are
	 * none before the first solve, since "how much is a stationary orbit" has no
	 * answer without an arc.
	 */
	function priceEnd(role: 'origin' | 'target', choice: OrbitChoice): number | null {
		// Before a trajectory is chosen the balanced one stands in for the trip:
		// which orbit is cheap depends on how fast the arc is going when it gets
		// there, and the fast route's excess speed would price every choice as
		// though the reader had already picked the most expensive way to travel.
		const route =
			panel.selectedRoute ??
			panel.offered.find((o) => o.profile === 'balanced')?.route ??
			panel.offered[0]?.route ??
			null;
		const body = role === 'origin' ? originTravel : targetTravel;
		if (!route || !body || !choice.orbit) return null;
		if (role === 'target') {
			const mode = choice.kind === 'elliptical' ? 'capture' : 'low-orbit';
			return arrivalCost(body, route.vInfArrKms, mode, panel.effectiveAero, choice.orbit)
				.captureKms;
		}
		return departureCost(body, route.vInfDepKms, 'orbit', choice.orbit).injectionKms;
	}

	// A flyby never slows down, so there is nothing for an atmosphere to do. A
	// destination whose envelope the kernel would ignore must not show the
	// control either — the same gate `canAeroBrake` applies. Asked of the detail
	// bundle rather than `targetTravel`, which is rebuilt from the scene's body
	// index and briefly resolves to nothing; a control that vanishes and comes
	// back between a press and its release swallows the click.
	let targetHasAir = $derived(
		(aeroPressurePa(targetDetail) ?? 0) >= travelConstants.AERO_MIN_PRESSURE_PA
	);
	let isLanding = $derived(panel.targetAtSite || panel.targetMode === 'surface');
	let showAero = $derived(targetHasAir && panel.targetMode !== 'flyby');
	// Ordered by how much of the arrival is still flown on the engine: all of it,
	// then the capture burn only, then none of it. Aerobraking walks a loose orbit
	// down into a tight one, so it is only on offer when a tight one is what was
	// asked for.
	let aeroChoices = $derived([
		{ value: 'none' as const, label: m.travel_aero_none() },
		...(panel.aerobrakingApplies
			? [{ value: 'aerobraking' as const, label: m.travel_aero_aerobraking() }]
			: []),
		{
			value: 'aerocapture' as const,
			label: isLanding ? m.travel_aero_direct_entry() : m.travel_aero_aerocapture()
		}
	]);
	// A trip that was aerobraking and is now landing is not braking on the way in
	// at all until it says so again — and what the control shows is exactly what
	// the routes are priced with.
	let aeroValue = $derived(panel.effectiveAero);
	// Candidates for a swing-by. Only a heliocentric trip gets any: inside one
	// system the transfer already goes round the only body massive enough to
	// bend it. No detail bundle is fetched for them — the only thing one would
	// add is an atmosphere, and nothing lands on a body it swings past.
	let assistBodies = $derived.by<TravelBody[]>(() => {
		const bodies = bodiesById;
		const heliocentric = frame.orbit === 'heliocentric';
		// Untracked, and load-bearing: a candidate on screen is the scene's own row,
		// rewritten as the clock runs, so reading it here would make the search a
		// function of the clock — and it takes about a second, so a list that
		// changed twice a second would never finish one.
		return untrack(() => {
			if (!heliocentric) return [];
			const lookup = lookupIn(bodies);
			const out: TravelBody[] = [];
			for (const id of ASSIST_BODY_IDS) {
				const body = bodies.get(id);
				if (!body) continue;
				const travel = toTravelBody(body, lookup);
				if (travel) out.push(travel);
			}
			return out;
		});
	});

	// A trip at one body with no arc between its ends: the same orbit twice, or
	// two points on the ground, which is a hop rather than an orbit change.
	let samePlace = $derived(
		plan?.kind === 'orbit-change' &&
			originTravel !== null &&
			orbitChangeEnds(originTravel, {
				departureMode: panel.departureMode,
				arrivalMode: panel.arrivalMode,
				...panel.endTerms
			}) === null
	);
	/** Which of the two same-body nothings it is: a hop between two points on the
	 *  ground, or the one orbit named at both ends. */
	let surfaceHop = $derived(panel.departureMode === 'surface' && panel.arrivalMode === 'landing');

	// An end that never resolved is an end with no orbit, not an empty form. The
	// destination is asked for first: it is the question the panel exists to
	// answer, and a departure with nowhere to go prices nothing.
	let block = $derived<BlockReason | null>(
		plan === null
			? !targetPicked
				? 'no-target'
				: !originPicked
					? 'no-origin'
					: 'unknown-orbit'
			: samePlace
				? surfaceHop
					? 'surface-hop'
					: 'same-place'
				: plan.kind === 'blocked'
					? plan.reason
					: null
	);

	// A trip out to a body's own moon waits for nothing: the satellite comes round
	// every orbit, so every departure date is a window and naming one would be
	// noise. Two moons of one planet do have alignments, just fast ones.
	let nextWindowJd = $derived.by(() => {
		// A trip between two orbits about one body waits for nothing either: the
		// pair of burns is there on every revolution.
		if (!originTravel || !targetTravel || block || frame.systemPrimary || frame.orbitChange) {
			return null;
		}
		const windows = nextTransferWindows(originTravel, targetTravel, nowJd, 1, frame.centralMu);
		return windows.length > 0 ? windows[0] : null;
	});

	// A deadline in the present admits nothing, so "arrive by" opens one slowest
	// transfer out — the earliest date the trip could plausibly be held to.
	function defaultPickedJd(mode: TimeMode): number {
		if (mode !== 'arrive' || !originTravel || !targetTravel) return nowJd;
		if (frame.orbitChange) {
			// The half-ellipse between the two orbits is the slowest crossing here,
			// and the only one a deadline has to admit.
			const ends = orbitChangeEnds(originTravel, {
				departureMode: panel.departureMode,
				arrivalMode: panel.arrivalMode,
				...panel.endTerms
			});
			if (!ends || ends.singleBurn) return nowJd;
			return (
				nowJd +
				hohmannArcDays(
					originTravel.mu,
					Math.min(ends.rFromKm, ends.rToKm),
					Math.max(ends.rFromKm, ends.rToKm)
				)
			);
		}
		const slowest = frame.systemPrimary
			? (systemArcBounds(
					frame.systemPrimary === 'departure' ? originTravel : targetTravel,
					frame.systemPrimary === 'departure' ? targetTravel : originTravel,
					nowJd
				)?.slowestDays ?? null)
			: (transferScale(originTravel, targetTravel, nowJd, frame.centralMu)?.days ?? null);
		return nowJd + (slowest ?? 0);
	}

	// The kernel's view of an end at one of the dates the search arrived at. The
	// two ends are read at different dates on purpose: what a transfer needs is
	// where the origin is when it leaves and where the destination is when it
	// gets there, and for anything that does not keep still those are described
	// by different elements.
	async function refineEnd(role: 'origin' | 'target', jd: number): Promise<TravelBody | null> {
		const body = role === 'origin' ? origin : target;
		if (!body || !refineBody) return null;
		const fresh = await refineBody(body.id, jd);
		if (!fresh) return null;
		// Measured positions outrank any re-description of the elements, and the
		// pass they are handed to prices the whole crossing against them.
		return measured(
			toTravelBody(fresh, lookup, role === 'origin' ? originDetail : targetDetail, frame.orbit)
		);
	}

	/** What to put to the panel: one whole question, or the reason there isn't
	 *  one. An end that never resolved has no orbit to leave from. */
	let job = $derived<{ block: BlockReason } | { request: SolveRequest }>(
		block
			? { block }
			: originTravel && targetTravel
				? {
						request: {
							origin: originTravel,
							target: targetTravel,
							nowJd,
							frame,
							terms: panel.solveTerms
						}
					}
				: { block: 'unknown-orbit' }
	);

	// One effect owns re-solving, and it turns on this key alone. Content, not
	// identity: the ends are rebuilt whenever the scene re-describes a body, and
	// a porkchop is far too expensive to redo because an equal object arrived.
	let solveKey = $derived('block' in job ? `blocked|${job.block}` : solveRequestKey(job.request));

	$effect(() => {
		void solveKey;
		untrack(() => {
			if ('block' in job) panel.block(job.block);
			else void panel.solve(job.request, refineEnd);
		});
	});

	// The two trajectories that come off the craft are their own effect: they
	// turn on the ship, which the solve above deliberately ignores, and answer
	// without a worker so they cost nothing to redo. Cargo is read for the
	// spiral alone — the one trajectory a loaded hold makes slower as well as
	// dearer.
	$effect(() => {
		const from = pathOrigin;
		const to = pathTarget;
		const payloadKg = panel.payloadKg;
		const siteLats = [panel.originSiteLatDeg, panel.targetSiteLatDeg];
		void payloadKg;
		void siteLats;
		if (block || !from || !to) {
			panel.torchPresets = [];
			panel.torchCustom = null;
			panel.spiral = null;
			return;
		}
		panel.updateTorch(from, to, nowJd, frame);
		panel.updateSpiral(from, to, nowJd, frame);
	});

	// A fourth effect for the coast alone. It is the one input that moves under a
	// drag, and a drag must not re-solve the presets on every frame.
	$effect(() => {
		const from = pathOrigin;
		const to = pathTarget;
		const coast = panel.coastFraction;
		void coast;
		if (block || !from || !to) {
			panel.torchCustom = null;
			return;
		}
		panel.updateTorchCustom(from, to, nowJd, frame);
	});

	// And the swing-by hunt is a third, for the same reason again: it sweeps a
	// decade of departures per candidate body and answers about a second later, so
	// the three direct routes must not be held up waiting for it. The craft is not
	// among its inputs — a different ship flies the same trajectory.
	$effect(() => {
		const from = pathOrigin;
		const to = pathTarget;
		const vias = assistBodies;
		const departure = panel.originMode;
		const arrival = panel.targetMode;
		// Braking is among them: the hunt is judged against the direct routes, and
		// they are priced with it.
		const braking = panel.effectiveAero;
		const siteLats = [panel.originSiteLatDeg, panel.targetSiteLatDeg];
		void departure;
		void arrival;
		void braking;
		void siteLats;

		// A swing-by buys speed towards somewhere else; a trip that stays at one
		// body has nowhere for it to buy speed towards.
		if (block || !from || !to || vias.length === 0 || frame.orbitChange) {
			panel.clearAssist();
			return;
		}
		void panel.updateAssist(from, to, vias, nowJd, { centralMu: frame.centralMu });
	});

	$effect(() => () => panel.dispose());

	// The frame every drawn arc is measured from — which is not the body the
	// pricing calls the centre, but the one the elements are referenced to.
	let centerId = $derived(
		plan && origin && target ? transferCenterId(plan, origin, target, lookup) : null
	);

	/** A route as the map takes it: geometry, plus what to write at each end.
	 *  `onSelect` is what makes it an offer rather than the plan. */
	function labelled(
		id: string,
		route: Route,
		path: TrajectoryPath,
		offer?: { onSelect: () => void; onHover: (hovered: boolean) => void }
	): LabelledPath {
		return {
			id,
			path,
			departure: { name: originName ?? '', when: formatJulianDate(route.departJd) },
			arrival: { name: targetName ?? '', when: formatJulianDate(route.arriveJd) },
			...offer
		};
	}

	/** One route as geometry, or null when it cannot be drawn. */
	function buildPath(
		route: Route,
		center: string,
		pathFrame: TrajectoryFrame = 'interplanetary'
	): TrajectoryPath | null {
		if (!pathOrigin || !pathTarget) return null;
		return buildTrajectoryPath(pathOrigin, pathTarget, route, {
			centerId: center,
			centralMu: frame.centralMu,
			systemPrimary: frame.systemPrimary,
			orbitChange: frame.orbitChange,
			frame: pathFrame,
			// A swing-by route is drawn as two arcs meeting at a body neither end
			// is, so the geometry needs the same candidates the search had.
			vias: assistBodies,
			surfaceSites: {
				departure: originSiteAt ?? undefined,
				arrival: targetSiteAt ?? undefined
			}
		});
	}

	// The site coordinates land after the geometry is first drawn, the way the
	// names land after the labels; their arrival has to re-aim the ground leg.
	let sitesKey = $derived((originSiteAt ? 'o' : '') + (targetSiteAt ? 't' : ''));

	let pathKey = $derived.by(() => {
		const route = panel.selectedRoute;
		if (!route || !centerId) return null;
		// The end names are on the labels, and they land after the geometry does.
		return [
			originName ?? '',
			targetName ?? '',
			viewFrame,
			sitesKey,
			panel.pricedRevision,
			routeKey(route, centerId, frame)
		].join(';');
	});

	// The dates the drawn plan knows better than the priced legs — the timeline's
	// cards take these, so picking one shows the place its line is drawn at
	// instead of piling every arrival instant on the crossing's own date.
	let planDrawn = $state<DrawnDates | null>(null);

	// One effect owns the drawn path, the way one owns the solve. Everything it
	// reads beyond the key is untracked, so a route object replaced with an equal
	// one cannot get the geometry rebuilt behind the key's back.
	$effect(() => {
		const key = pathKey;
		untrack(() => {
			const route = panel.selectedRoute;
			if (key === null || !route || !centerId) {
				planDrawn = null;
				onPathChange(null);
				return;
			}
			const path = buildPath(route, centerId, viewFrame);
			if (!path) {
				console.warn(
					`[travel] no drawable path for ${route.departureId} → ${route.targetId} ` +
						`(depart ${route.departJd}, ${route.tofDays} d)`
				);
				planDrawn = null;
				onPathChange(null);
				return;
			}
			const departureEnd = path.endOrbits.find((end) => end.at === 'departure');
			const arrivalEnd = path.endOrbits.find((end) => end.at === 'arrival');
			planDrawn = {
				liftoffJd: departureEnd?.surfaceJd,
				touchdownJd: arrivalEnd?.surfaceJd,
				cruiseJd: departureEnd?.jds.at(-1),
				captureJd: arrivalEnd?.periJd,
				// The line's last date is the raise only while the trip ends in
				// orbit; a landing's runs on to the ground.
				raiseJd: arrivalEnd?.surfaceJd === undefined ? arrivalEnd?.jds.at(-1) : undefined
			};
			onPathChange(labelled(panel.selectedProfile ?? 'plan', route, path));
		});
	});

	// Every other trajectory on offer, which is what the map is for while the list
	// is up: a trajectory is a shape long before it is a set of figures, and seeing
	// the five of them at once is how the list gets read. They stay after one is
	// taken — the scene draws them faint by then — so the plan can be read against
	// what it beat.
	//
	// Keyed like the one above, and separately, so opening a trajectory does not
	// re-propagate the others and a re-solve that changes nothing rebuilds nothing.
	let alternatives = $derived(
		panel.offered.filter((choice) => choice.profile !== panel.selectedProfile)
	);
	let optionsKey = $derived.by(() => {
		if (!centerId) return null;
		const keys = alternatives.map((choice) => routeKey(choice.route, centerId, frame));
		// The end names are on the labels, and they land after the geometry does.
		return keys.length > 0
			? [originName ?? '', targetName ?? '', sitesKey, panel.pricedRevision, ...keys].join(';')
			: null;
	});

	$effect(() => {
		const key = optionsKey;
		untrack(() => {
			if (key === null || !centerId) {
				onOptionsChange([]);
				return;
			}
			const options: LabelledPath[] = [];
			for (const choice of alternatives) {
				const path = buildPath(choice.route, centerId);
				// A route that cannot be drawn is still a route: it keeps its row in the
				// list and simply contributes no line.
				if (!path) continue;
				const profile = choice.profile;
				options.push(
					labelled(profile, choice.route, path, {
						onSelect: () => panel.choose(profile),
						onHover: (hovered) => (hoveredProfile = hovered ? profile : null)
					})
				);
			}
			onOptionsChange(options);
		});
	});

	// What every trajectory on offer puts the craft through, not just the one
	// being read. Keyed separately from the two above: nothing here depends on
	// the end names, so a late-landing label must not cost six scans.
	let hazardsKey = $derived.by(() => {
		if (!centerId) return null;
		const keys = panel.offered.map((choice) => hazardKey(choice.route, centerId, frame));
		// The frame decides whether a distance from the centre is a distance from
		// the Sun, which is what half of these are read off.
		return keys.length > 0 ? [frame.orbit, panel.pricedRevision, ...keys].join(';') : null;
	});

	let hazardsByProfile = $state.raw<ReadonlyMap<RouteOption, Hazard[]>>(new Map());

	$effect(() => {
		const key = hazardsKey;
		untrack(() => {
			if (key === null || !centerId || !pathOrigin || !pathTarget) {
				hazardsByProfile = new Map();
				return;
			}
			const context = {
				centerId,
				centralMu: frame.centralMu,
				systemPrimary: frame.systemPrimary,
				orbitChange: frame.orbitChange,
				// A swing-by route is two arcs meeting at a body neither end is, so the
				// scan needs the same candidates the search had to rebuild the second.
				vias: assistBodies
			};
			const next = new Map<RouteOption, Hazard[]>();
			for (const choice of panel.offered) {
				next.set(choice.profile, routeHazards(pathOrigin, pathTarget, choice.route, context));
			}
			hazardsByProfile = next;
		});
	});

	// The chosen trajectory's own. Null profile is the list still being read, which
	// is a map with nothing to mark on it.
	let selectedHazards = $derived.by(() => {
		const profile = panel.selectedProfile;
		if (profile === null) return NO_HAZARDS;
		return hazardsByProfile.get(profile) ?? NO_HAZARDS;
	});

	$effect(() => {
		onHazardsChange(selectedHazards);
	});

	// The trip as its legs rather than as geometry. Keyed the same way and for the
	// same reason, but separately: a trajectory whose arc cannot be rebuilt still
	// has dates, and a timeline is the one part of it that can always be shown.
	let selectedTimelineKey = $derived.by(() => {
		const route = panel.selectedRoute;
		if (!route) return null;
		return timelineKey(route, originName, targetName, timelineBodies, planDrawn);
	});

	/** The two ends as the kernel knows them, once both are known. What the orbit
	 *  each end is flown from or into is derived from. */
	let timelineBodies = $derived(
		pathOrigin && pathTarget ? { departure: pathOrigin, target: pathTarget } : null
	);

	$effect(() => {
		const key = selectedTimelineKey;
		untrack(() => {
			const route = panel.selectedRoute;
			if (key === null || !route) {
				onTimelineChange(null);
				return;
			}
			onTimelineChange(
				buildTimeline(
					route,
					(bodyId) => {
						if (bodyId === origin?.id && originName) return originName;
						if (bodyId === target?.id && targetName) return targetName;
						return resolveBodyName(bodyId);
					},
					timelineBodies,
					planDrawn
				)
			);
		});
	});

	// Leaving the planner takes its trajectories off the map with it.
	$effect(() => () => onPathChange(null));
	$effect(() => () => onOptionsChange([]));
	$effect(() => () => onTimelineChange(null));
	$effect(() => () => onHazardsChange(NO_HAZARDS));

	// One end is enough: exchanging it with an empty one turns "going to Mars"
	// into "leaving Mars", which is how half a trip gets turned round.
	let anyEnd = $derived(originPicked || targetPicked);

	// Which of the two steps is showing. A trajectory is chosen or it is not, and
	// that is the whole of it — there is no third state where the form and the
	// trajectory are both up.
	let chosen = $derived(panel.selected);

	// Which family of trajectory is being read. Kept here rather than in the list,
	// which goes away whenever one is opened: stepping back should land on the tab
	// it was left on.
	let wantedFamily = $state<RouteFamily | null>(null);
	let tabs = $derived(routeTabs(panel.offered, panel.assistSearching));
	let family = $derived(activeFamily(tabs, wantedFamily));

	// Opening a trajectory says which tab the reader is in as surely as picking
	// one does — including a link that opened straight onto a swing-by, which
	// otherwise steps back to a tab it was never on.
	$effect(() => {
		const profile = chosen?.profile;
		if (profile) untrack(() => (wantedFamily = familyOf(profile)));
	});

	function swap() {
		// Modes ride along with their end, and every departure mode is also an
		// arrival one — so only the mode coming back needs a fallback, for the
		// three a departure cannot be: a flyby, a capture ellipse, a transfer orbit.
		const previousOriginMode = panel.originMode;
		const previousOriginAlt = panel.originAltKm;
		const previousOriginApo = panel.originApoAltKm;
		const previousOriginInc = panel.originIncDeg;
		panel.originMode = ORIGIN_MODES.includes(panel.targetMode) ? panel.targetMode : 'low-orbit';
		panel.targetMode = previousOriginMode;
		panel.originAltKm = panel.targetAltKm;
		panel.targetAltKm = previousOriginAlt;
		panel.originApoAltKm = panel.targetApoAltKm;
		panel.targetApoAltKm = previousOriginApo;
		// A plane is measured against its own body's equator, so it rides with the
		// end it belongs to rather than staying put.
		panel.originIncDeg = panel.targetIncDeg;
		panel.targetIncDeg = previousOriginInc;
		onSwap();
	}
</script>

<!-- The active family's rows, and the one control that belongs to a family
     rather than to a trajectory. -->
{#snippet trajectories()}
	<RouteList
		state={panel}
		{family}
		nameOf={resolveBodyName}
		hazardsFor={(profile) => hazardsByProfile.get(profile) ?? NO_HAZARDS}
		hovered={hoveredProfile}
		onHover={(id) => (hoveredProfile = id)}
		{nextWindowJd}
		onUseWindow={(jd: number) => {
			panel.timeMode = 'depart';
			panel.pickedJd = jd;
		}}
	/>
{/snippet}

<div class="flex flex-col gap-5">
	{#if chosen}
		{@const pass = chosen.route.flybys?.[0] ?? null}
		<!-- The title above names the trajectory. This line gives the two ends, their
		     modes and the dates. The picker is not on the screen in this step. -->
		<div class="flex flex-col gap-0.5">
			{#if originName && targetName}
				<!-- Each end is one block: a line too long for the drawer breaks
				     between them rather than mid-name, and both ends named in full
				     beats one of them cut off. -->
				<p class="text-sm">
					<span class="inline-block"
						>{originName}{#if originModeLabel}<span class="text-muted-foreground ms-1.5 text-xs"
								>{originModeLabel}</span
							>{/if}</span
					>
					<span class="inline-block"
						><MoveRightIcon
							class="inline size-[1em] align-[-0.125em] rtl:rotate-180"
							aria-hidden="true"
						/>&nbsp;{targetName}{#if targetModeLabel}<span
								class="text-muted-foreground ms-1.5 text-xs">{targetModeLabel}</span
							>{/if}{#if chosen.route.constantThrust}<span
								class="text-muted-foreground ms-1.5 text-xs tabular-nums"
								>{formatAcceleration(chosen.route.constantThrust)}</span
							>{:else if pass}<span class="text-muted-foreground ms-1.5 text-xs"
								>{m.travel_via({ body: resolveBodyName(pass.bodyId) })}</span
							>{/if}</span
					>
				</p>
			{/if}
			<p class="text-muted-foreground text-xs tabular-nums">
				{formatJulianDate(chosen.route.departJd)}
				<MoveRightIcon
					class="inline size-[1em] align-[-0.125em] rtl:rotate-180"
					aria-hidden="true"
				/>
				{formatJulianDate(chosen.route.arriveJd)}
			</p>
		</div>

		{#if originTravel && targetTravel}
			<RouteDetail
				route={chosen.route}
				origin={originTravel}
				target={targetTravel}
				state={panel}
				nameOf={resolveBodyName}
				{originName}
				hazards={selectedHazards}
			/>
		{/if}
	{:else}
		<!-- Every setup control is now a single row, so they take one even gap
		     between them rather than the wider one that separated blocks. -->
		<div class="flex flex-col gap-2.5">
			<!-- Three rows: origin, connector, destination. The swap sits beside all
	     three and spans them, so it reads as acting on the pair rather than on
	     the join between them, and stays centred however tall either box grows. -->
			<div class="grid grid-cols-[1fr_2rem] gap-x-2 gap-y-1.5">
				<div class="col-start-1 row-start-1 min-w-0">
					<EndpointField
						role="origin"
						fullscreen={isMobile}
						bodyName={originName}
						placeholder={m.travel_choose_origin()}
						isFeature={panel.originAtSite}
						mode={panel.originMode}
						onModeChange={(mode: EndpointMode) => (panel.originMode = mode)}
						choices={originChoices}
						customAltKm={panel.originAltKm}
						customApoAltKm={panel.originApoAltKm}
						maxAltKm={originTravel && originFacts
							? maxCustomAltitudeKm(originTravel, originFacts)
							: 0}
						onCustomAlt={(km: number) => (panel.originAltKm = km)}
						onCustomApoAlt={(km: number) => (panel.originApoAltKm = km)}
						incDeg={panel.originIncDeg}
						onIncChange={(deg: number | null) => (panel.originIncDeg = deg)}
						priceKms={(choice: OrbitChoice) => priceEnd('origin', choice)}
						open={openField === 'origin'}
						onOpenChange={(next: boolean) => setOpenField('origin', next)}
						excludeIds={excludeForOrigin}
						pads={originPads}
						padCode={originPadCode}
						groundLine={originGroundLine}
						onPadPick={onOriginPadPick}
						onPick={(pick) => {
							onOriginChange(pick);
							// A feature has already answered "how"; anything else moves on to it.
							if (pick.featureId !== null) openField = null;
						}}
					/>
				</div>

				<div class="col-start-1 row-start-2">
					<!-- 18px puts the stub under the endpoint markers' centre: the boxes'
				     px-2.5 plus half their size-3.5 marker cell. -->
					<span class="bg-border ms-[18px] block h-2.5 w-px" aria-hidden="true"></span>
				</div>

				<div class="col-start-1 row-start-3 min-w-0">
					<EndpointField
						role="target"
						fullscreen={isMobile}
						bodyName={targetName}
						placeholder={m.travel_choose_target()}
						isFeature={panel.targetAtSite}
						mode={panel.targetMode}
						onModeChange={(mode: EndpointMode) => (panel.targetMode = mode)}
						choices={targetChoices}
						customAltKm={panel.targetAltKm}
						customApoAltKm={panel.targetApoAltKm}
						maxAltKm={targetTravel && targetFacts
							? maxCustomAltitudeKm(targetTravel, targetFacts)
							: 0}
						onCustomAlt={(km: number) => (panel.targetAltKm = km)}
						onCustomApoAlt={(km: number) => (panel.targetApoAltKm = km)}
						incDeg={panel.targetIncDeg}
						onIncChange={(deg: number | null) => (panel.targetIncDeg = deg)}
						priceKms={(choice: OrbitChoice) => priceEnd('target', choice)}
						open={openField === 'target'}
						onOpenChange={(next: boolean) => setOpenField('target', next)}
						excludeIds={excludeForTarget}
						pads={targetPads}
						padCode={targetPadCode}
						groundLine={targetGroundLine}
						onPadPick={onTargetPadPick}
						onPick={(pick) => {
							onTargetChange(pick);
							if (pick.featureId !== null) openField = null;
						}}
					/>
				</div>

				<div class="col-start-2 row-span-3 row-start-1 flex items-center justify-end">
					<Button
						variant="outline"
						size="icon"
						onclick={swap}
						disabled={!anyEnd}
						class="text-muted-foreground"
						aria-label={m.travel_swap()}
					>
						<ArrowUpDownIcon />
					</Button>
				</div>
			</div>

			<!-- When and how it arrives are one line: two phrases with their menus,
		     rather than two banks of buttons. Both are terms of the trip that most
		     readers never change, so they state the answer and stay out of the way
		     of the trajectories.

		     The line always stands as tall as the date pill, which only two of the
		     three timing modes show — otherwise picking one of them would shunt
		     everything below it down by ten pixels.

		     It wraps rather than holding one line at any cost: on a narrow phone a
		     date and a braking mode together outrun the width, and a control shoved
		     off the end is gone rather than merely cramped. -->
			<div class="flex min-h-6.5 flex-wrap items-center gap-2">
				<TimingField
					mode={panel.timeMode}
					jd={panel.pickedJd ?? defaultPickedJd(panel.timeMode)}
					onModeChange={(mode: TimeMode) => {
						panel.timeMode = mode;
						// Seed the date on the way in, so the mode means something the moment
						// it is chosen rather than after a second click.
						if (mode !== 'now' && panel.pickedJd == null) panel.pickedJd = defaultPickedJd(mode);
					}}
					onDateChange={(jd: number) => (panel.pickedJd = jd)}
				/>
				{#if showAero}
					<!-- Trailing, muted, and second: braking answers the arrival, which is
				     the later half of the same sentence the timing starts. Pushed to the
				     end by its own margin rather than by a spacer, which would eat a
				     whole line to itself once the row wraps. -->
					<span class="ms-auto">
						<InlineMenu
							options={aeroChoices}
							value={aeroValue}
							onchange={(aero: AeroAssist) => (panel.aero = aero)}
							ariaLabel={m.travel_aero_assist()}
							align="end"
							muted
						/>
					</span>
				{/if}
			</div>

			<div class="flex flex-col gap-2.5">
				<!-- Above the craft, and beside it rather than inside it: what you are
			     taking is a fact about the trip that stands on its own before one is
			     chosen, and it is what narrows the catalogue down — so it is asked
			     first, and the list below it is already the list that can carry it. -->
				<ManifestField
					passengers={panel.passengers}
					payloadKg={panel.payloadKg}
					fit={panel.manifestFit}
					onPassengersChange={(value) => (panel.passengers = value)}
					onPayloadChange={(value) => (panel.payloadKg = value)}
				/>

				<VehicleField
					fullscreen={isMobile}
					vehicles={shownVehicles}
					loaded={panel.vehiclesReady}
					selected={panel.vehicle}
					route={panel.selectedRoute}
					manifest={panel.manifest}
					passengers={panel.passengers}
					departureMode={panel.departureMode}
					onSelect={(id) => panel.selectVehicle(id)}
					open={openField === 'craft'}
					onOpenChange={(next: boolean) => {
						setOpenField('craft', next);
						// Nothing waits on this — the routes are already solved, and the list
						// fills in when it lands.
						if (next) void panel.loadVehicles();
					}}
				/>
			</div>

			{#if panel.status === 'blocked'}
				<!-- An end left blank is a prompt, not a failure — no alert icon on it. -->
				{#if panel.blocked === 'no-target'}
					<p class="text-muted-foreground text-xs">{m.travel_no_target()}</p>
				{:else if panel.blocked === 'no-origin'}
					<p class="text-muted-foreground text-xs">{m.travel_no_origin()}</p>
					<!-- Also a prompt rather than a failure: the two ends are the same place,
			     and moving either one is the whole fix. -->
				{:else if panel.blocked === 'same-place'}
					<p class="text-muted-foreground text-xs">{m.travel_same_place()}</p>
				{:else if panel.blocked === 'surface-hop'}
					<p class="text-muted-foreground text-xs">{m.travel_surface_hop()}</p>
				{:else}
					<p class="text-muted-foreground flex items-start gap-2 text-xs">
						<CircleAlertIcon class="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
						<span>
							{panel.blocked === 'unknown-primary'
								? m.travel_unknown_primary()
								: m.travel_unknown_orbit()}
						</span>
					</p>
				{/if}
				<!-- Counted against everything offered rather than against the search: a
		     constant-thrust arc needs no grid, so it can be the only answer there
		     is while the porkchop is still running. -->
			{:else if panel.status === 'solving' && panel.offered.length === 0}
				<p class="text-muted-foreground text-xs">{m.travel_solving()}</p>
			{:else if panel.status !== 'idle' && panel.offered.length === 0}
				<!-- On the offer list rather than on `status`: a route can be withdrawn
			     after a solve answered — a longer coast missing the deadline — and
			     the panel still has to say so rather than go blank. -->
				<!-- Which of the two nothings this is: the pair has no transfer at all, or
			     it has them and they are all too slow for the date asked for. -->
				<p class="text-muted-foreground text-xs">
					{panel.missedDeadline ? m.travel_no_routes_by_date() : m.travel_no_routes()}
				</p>
				<!-- A coast long enough to miss the deadline is what took the arc off the
			     list, so the control that did it has to outlive the list. -->
				{#if panel.torchMissedDeadline}<CruiseBox state={panel} />{/if}
			{:else if panel.offered.length > 0}
				<!-- Said above the list rather than instead of it: what is left when the
			     search found nothing in time is a hand-picked point or a craft's own
			     arc, and neither of them answers for the search. -->
				{#if panel.missedDeadline}
					<p class="text-muted-foreground text-xs">{m.travel_no_routes_by_date()}</p>
				{/if}
				<!-- The arc is gone, so its tab is too, and the control that took it has
			     nowhere left to live but over the list. -->
				{#if panel.torchMissedDeadline}<CruiseBox state={panel} />{/if}
				<!-- One family of trajectory is on offer often enough — a chemical craft
			     with no swing-by to be had — that a single tab would be a control
			     with nothing to choose. -->
				{#if tabs.length > 1}
					<RouteTabs {tabs} active={family} onSelect={(next) => (wantedFamily = next)}>
						{@render trajectories()}
					</RouteTabs>
				{:else}
					<div class="flex flex-col gap-2">{@render trajectories()}</div>
				{/if}
			{/if}
		</div>
	{/if}
</div>
