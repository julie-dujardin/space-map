<!--
  The travel panel: describe a trip, get trajectories.

  Two steps. The first describes the trip and lists what could fly it, with all
  of those trajectories drawn on the map at once. Choosing one replaces the whole
  form with that trajectory in detail, and the map with that arc and its
  timeline. `panel.selectedRoute` is which step is showing: a trajectory is being
  read, or they are still being chosen between.

  The whole trip is a link: its two ends are the path (`/nav/<from>/<to>`) and
  everything below the endpoint fields — when to go, what to fly, what it
  carries, which trajectory is being read — is the query. The panel owns the
  live state and mirrors it out; the URL is how it comes back.
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import ArrowUpDownIcon from '@lucide/svelte/icons/arrow-up-down';
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import RocketIcon from '@lucide/svelte/icons/rocket';
	import CheckIcon from '@lucide/svelte/icons/check';
	import CircleAlertIcon from '@lucide/svelte/icons/circle-alert';
	import UsersIcon from '@lucide/svelte/icons/users';
	import type { BodyData } from '$lib/types/objects';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { formatJulianDate } from '$lib/format/date';
	import {
		arrivalCost,
		buildTrajectoryPath,
		canDepartFrom,
		checkFeasibility,
		departureCost,
		crewCapacity,
		nextTransferWindows,
		systemArcBounds,
		transferScale,
		type AeroAssist,
		type Route,
		type TrajectoryPath,
		type TravelBody
	} from '$lib/math/travel';
	import {
		hasAtmosphere,
		lookupIn,
		toTravelBody,
		transferCenterId,
		transferFrame,
		transferPlan,
		type TransferFrame,
		type TransferPlan
	} from '$lib/travel/travel-body';
	import { TravelPanelState, type BlockReason } from '$lib/travel/panel.svelte';
	import { ASSIST_BODY_IDS } from '$lib/travel/assist-bodies';
	import {
		ORIGIN_MODES,
		serializeTripSuffix,
		type EndpointMode,
		type TimeMode,
		type TripState
	} from '$lib/travel/trip';
	import type { TravelEndpointPick } from '$lib/travel/endpoint';
	import {
		hasGround,
		maxCustomAltitudeKm,
		orbitChoices,
		orbitFacts,
		type OrbitChoice
	} from '$lib/travel/orbits';
	import { buildTimeline, type TimelineEntry } from '$lib/travel/timeline';
	import type { LabelledPath } from '$lib/travel/labelled-path';
	import { formatAcceleration } from '$lib/travel/format';
	import { departureNote, vehicleName } from './vehicle-labels';
	import { Button } from '$lib/components/ui/button/index.js';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import { Slider } from '$lib/components/ui/slider/index.js';
	import { formatDurationNarrow } from '$lib/format/duration';
	import { formatPercent } from '$lib/format/quantities';
	import Segmented from './Segmented.svelte';
	import VehicleMeta from './VehicleMeta.svelte';
	import DateField from './DateField.svelte';
	import ManifestField from './ManifestField.svelte';
	import EndpointField from './EndpointField.svelte';
	import RouteList from './RouteList.svelte';
	import RouteDetail from './RouteDetail.svelte';
	import PorkchopChart from './PorkchopChart.svelte';
	import { routeLabel } from './route-labels';

	interface Props {
		/** Where the trip starts; null until one is chosen. */
		origin: BodyData | null;
		/** Where it ends; null until one is chosen. */
		target: BodyData | null;
		/** Localized labels for the two ends. */
		originName: string | null;
		targetName: string | null;
		/** IAU feature id when an end is a named place on its body's surface. */
		originFeatureId: number | null;
		targetFeatureId: number | null;
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
		/** What a body passed on the way is called. The two ends name themselves;
		 *  this is for the ones in between — the body a swing-by goes past. */
		resolveBodyName: (bodyId: string) => string;
	}
	let {
		origin,
		target,
		originName,
		targetName,
		originFeatureId,
		targetFeatureId,
		originPicked,
		targetPicked,
		bodiesById,
		nowJd,
		excludeForOrigin,
		excludeForTarget,
		originDetail = null,
		targetDetail = null,
		trip,
		onOriginChange,
		onTargetChange,
		onSwap,
		onTripChange,
		onPathChange,
		onOptionsChange,
		onHoverChange,
		onTimelineChange,
		resolveBodyName
	}: Props = $props();

	// Seeded once; from here on the two are kept in step by the effects below.
	const panel = new TravelPanelState(untrack(() => trip));

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
	let openField = $state<'origin' | 'target' | null>(null);

	/**
	 * Only one box is open at a time, and the one closing may not be the one that
	 * just opened: clicking the other box opens it and *then* tells this one it
	 * closed, so an unguarded assignment shuts the box the click was for.
	 */
	function setOpenField(field: 'origin' | 'target', open: boolean) {
		if (open) openField = field;
		else if (openField === field) openField = null;
	}
	// The empty fourth route row sends the reader here, so the list needs a handle
	// on the chart below it.
	let chart = $state<ReturnType<typeof PorkchopChart> | null>(null);

	// The URL decides whether an end is a place on a surface; the panel state
	// mirrors it so the mode getters and the field's own rendering agree.
	$effect(() => {
		panel.originIsFeature = originFeatureId !== null;
		panel.targetIsFeature = targetFeatureId !== null;
	});

	let vehicleOpen = $state(false);

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

	// The kernel's view of each end, rebuilt whenever either body or its detail
	// changes.
	let originTravel = $derived<TravelBody | null>(
		origin ? toTravelBody(origin, lookup, originDetail, frame.orbit) : null
	);
	let targetTravel = $derived<TravelBody | null>(
		target ? toTravelBody(target, lookup, targetDetail, frame.orbit) : null
	);

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
		originTravel && originFacts && !panel.originIsFeature
			? orbitChoices(originTravel, originFacts, 'origin', {
					hasSurface: originHasGround,
					customAltKm: panel.originAltKm
				})
			: []
	);
	let targetChoices = $derived<OrbitChoice[]>(
		targetTravel && targetFacts && !panel.targetIsFeature
			? orbitChoices(targetTravel, targetFacts, 'target', {
					hasSurface: targetHasGround,
					customAltKm: panel.targetAltKm
				})
			: []
	);

	/**
	 * A mode the body cannot hold is not a mode: a link naming a stationary orbit
	 * at Venus falls back to the low one rather than labelling a trip it is not
	 * pricing.
	 *
	 * Guarded on the detail bundle having landed, and load-bearing. The spin that
	 * says whether a stationary orbit exists arrives with that bundle, so during
	 * the wait *every* named orbit is missing from the list — and an unguarded
	 * check would read that as "Earth has no geostationary orbit" and quietly
	 * rewrite a shared link's own mode on the way in.
	 */
	$effect(() => {
		if (!originDetail || !originChoices.length) return;
		if (!originChoices.some((c) => c.kind === panel.originMode)) panel.originMode = 'low-orbit';
	});
	$effect(() => {
		if (!targetDetail || !targetChoices.length) return;
		if (!targetChoices.some((c) => c.kind === panel.targetMode)) panel.targetMode = 'low-orbit';
	});

	// The orbit each end is met in, handed to the panel so every builder prices
	// the same one. A mode with no orbit of its own — a landing, a flyby — leaves
	// it unset and the kernel falls back to its parking orbit.
	$effect(() => {
		panel.originOrbit = originChoices.find((c) => c.kind === panel.originMode)?.orbit;
	});
	$effect(() => {
		panel.targetOrbit = targetChoices.find((c) => c.kind === panel.targetMode)?.orbit;
	});

	/**
	 * What each orbit would cost at this end, on the trajectory being read.
	 *
	 * Priced from the excess speed the chosen route arrives with, so the figures
	 * move with the trajectory rather than standing for a trip nobody picked —
	 * and there are none at all before the first solve, which is honest: the
	 * question "how much is a stationary orbit" has no answer without an arc.
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
			return arrivalCost(body, route.vInfArrKms, mode, panel.aero, choice.orbit).captureKms;
		}
		return departureCost(body, route.vInfDepKms, 'orbit', choice.orbit).injectionKms;
	}

	// A flyby never slows down, so there is nothing for an atmosphere to do. A
	// destination with none of its own ignores the request anyway, and offering it
	// would be asking a question with one answer.
	// Asked of the destination's own detail bundle rather than of `targetTravel`.
	// That is rebuilt from the scene's body index, which churns and briefly
	// resolves to nothing — and a control that vanishes and comes back between a
	// press and its release swallows the click that was on it.
	let targetHasAir = $derived(hasAtmosphere(targetDetail) === true);
	let isLanding = $derived(panel.targetIsFeature || panel.targetMode === 'surface');
	let showAero = $derived(targetHasAir && panel.targetMode !== 'flyby');
	// Ordered by how much of the arrival is still flown on the engine: all of it,
	// then the capture burn only, then none of it. Aerobraking walks a loose orbit
	// down into a tight one, so it is only on offer when a tight one is what was
	// asked for.
	let aeroChoices = $derived([
		{ value: 'none' as const, label: m.travel_aero_none() },
		...(panel.targetMode === 'low-orbit'
			? [{ value: 'aerobraking' as const, label: m.travel_aero_aerobraking() }]
			: []),
		{
			value: 'aerocapture' as const,
			label: isLanding ? m.travel_aero_direct_entry() : m.travel_aero_aerocapture()
		}
	]);
	// A trip that was aerobraking and is now landing is not braking on the way in
	// at all until it says so again.
	let aeroValue = $derived(
		panel.aero === 'aerobraking' && panel.targetMode !== 'low-orbit' ? 'none' : panel.aero
	);
	// Candidates for a swing-by. Only a heliocentric trip gets any: inside one
	// system the transfer already goes round the only body massive enough to bend
	// it, and there is nothing left to pass on the way.
	//
	// No detail bundle is fetched for them — the only thing one would add is an
	// atmosphere, and nothing lands on a body it swings past.
	let assistBodies = $derived.by<TravelBody[]>(() => {
		const bodies = bodiesById;
		const heliocentric = frame.orbit === 'heliocentric';
		// Untracked, and load-bearing. A candidate that is on screen is the scene's
		// own row, and the scene rewrites its elements as the clock runs — so
		// reading them here would make this list, and the search that depends on it,
		// a function of the clock. The search takes about a second and a new one
		// stops the last, so a list that changed twice a second would never finish
		// one. The map identity is the whole dependency.
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
			: plan.kind === 'blocked'
				? plan.reason
				: null
	);

	// A trip out to a body's own moon waits for nothing: the satellite comes round
	// every orbit, so every departure date is a window and naming one would be
	// noise. Two moons of one planet do have alignments, just fast ones.
	let nextWindowJd = $derived.by(() => {
		if (!originTravel || !targetTravel || block || frame.systemPrimary) return null;
		const windows = nextTransferWindows(originTravel, targetTravel, nowJd, 1, frame.centralMu);
		return windows.length > 0 ? windows[0] : null;
	});

	const TIME_MODES: { value: TimeMode; label: string }[] = [
		{ value: 'now', label: m.travel_time_now() },
		{ value: 'depart', label: m.travel_time_depart() },
		{ value: 'arrive', label: m.travel_time_arrive() }
	];

	// A deadline in the present admits nothing, so "arrive by" opens one slowest
	// transfer out — the earliest date the trip could plausibly be held to.
	function defaultPickedJd(mode: TimeMode): number {
		if (mode !== 'arrive' || !originTravel || !targetTravel) return nowJd;
		const slowest = frame.systemPrimary
			? (systemArcBounds(
					frame.systemPrimary === 'departure' ? originTravel : targetTravel,
					frame.systemPrimary === 'departure' ? targetTravel : originTravel,
					nowJd
				)?.slowestDays ?? null)
			: (transferScale(originTravel, targetTravel, nowJd, frame.centralMu)?.days ?? null);
		return nowJd + (slowest ?? 0);
	}

	// One effect owns re-solving, so every input that should trigger one is
	// listed here rather than hidden behind an async write elsewhere.
	$effect(() => {
		const from = originTravel;
		const to = targetTravel;
		const blocking = block;
		const mode = panel.timeMode;
		const picked = panel.pickedJd;
		const departure = panel.originMode;
		const arrival = panel.targetMode;
		const aero = panel.aero;
		void mode;
		void picked;
		void departure;
		void arrival;
		void aero;

		if (blocking) {
			panel.block(blocking);
			return;
		}
		if (!from || !to) {
			panel.block('unknown-orbit');
			return;
		}
		void panel.solve(from, to, nowJd, frame);
	});

	// The two trajectories that come off the craft are their own effect: they turn
	// on the ship, which the solve above deliberately ignores — a different ship is
	// not a different search — and they answer without a worker, so they cost
	// nothing to redo. The cargo is read for the spiral alone, which is the one
	// trajectory a loaded hold makes slower as well as dearer.
	$effect(() => {
		const from = originTravel;
		const to = targetTravel;
		const payloadKg = panel.payloadKg;
		void payloadKg;
		if (block || !from || !to) {
			panel.torch = null;
			panel.spiral = null;
			return;
		}
		panel.updateTorch(from, to, nowJd, frame);
		panel.updateSpiral(from, to, nowJd, frame);
	});

	// And the swing-by hunt is a third, for the same reason again: it sweeps a
	// decade of departures per candidate body and answers about a second later, so
	// the three direct routes must not be held up waiting for it. The craft is not
	// among its inputs — a different ship flies the same trajectory.
	$effect(() => {
		const from = originTravel;
		const to = targetTravel;
		const vias = assistBodies;
		const departure = panel.originMode;
		const arrival = panel.targetMode;
		// Braking is among them: the hunt is judged against the direct routes, and
		// they are priced with it.
		const braking = panel.aero;
		void departure;
		void arrival;
		void braking;

		if (block || !from || !to || vias.length === 0) {
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

	// What the map is drawing, and what would change it. The solve effect above
	// re-runs several times a second, handing back a fresh (and usually identical)
	// route object each time; rebuilding a few hundred propagated points off every
	// one of those would be work nobody asked for. So the geometry is keyed on
	// what actually shapes it, and only a change in the key rebuilds.
	function routeKey(route: Route, center: string, transfer: TransferFrame): string {
		const via = route.flybys?.[0];
		return [
			center,
			route.departureId,
			route.targetId,
			route.departJd,
			route.tofDays,
			route.departureMode,
			route.arrivalMode,
			route.constantThrust ?? '',
			route.lowThrust?.accelMs2 ?? '',
			via ? `${via.bodyId}@${via.jd}` : '',
			transfer.systemPrimary ?? '',
			transfer.centralMu ?? ''
		].join('|');
	}

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
	function buildPath(route: Route, center: string): TrajectoryPath | null {
		if (!originTravel || !targetTravel) return null;
		return buildTrajectoryPath(originTravel, targetTravel, route, {
			centerId: center,
			centralMu: frame.centralMu,
			systemPrimary: frame.systemPrimary,
			// A swing-by route is drawn as two arcs meeting at a body neither end
			// is, so the geometry needs the same candidates the search had.
			vias: assistBodies
		});
	}

	let pathKey = $derived.by(() => {
		const route = panel.selectedRoute;
		if (!route || !centerId) return null;
		// The end names are on the labels, and they land after the geometry does.
		return [originName ?? '', targetName ?? '', routeKey(route, centerId, frame)].join(';');
	});

	// One effect owns the drawn path, the way one owns the solve. Everything it
	// reads beyond the key is untracked, so a route object replaced with an equal
	// one cannot get the geometry rebuilt behind the key's back.
	$effect(() => {
		const key = pathKey;
		untrack(() => {
			const route = panel.selectedRoute;
			if (key === null || !route || !centerId) {
				onPathChange(null);
				return;
			}
			const path = buildPath(route, centerId);
			if (!path) {
				console.warn(
					`[travel] no drawable path for ${route.departureId} → ${route.targetId} ` +
						`(depart ${route.departJd}, ${route.tofDays} d)`
				);
				onPathChange(null);
				return;
			}
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
		return keys.length > 0 ? [originName ?? '', targetName ?? '', ...keys].join(';') : null;
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

	// The trip as its legs rather than as geometry. Keyed the same way and for the
	// same reason, but separately: a trajectory whose arc cannot be rebuilt still
	// has dates, and a timeline is the one part of it that can always be shown.
	let timelineKey = $derived.by(() => {
		const route = panel.selectedRoute;
		if (!route) return null;
		return [
			route.departureId,
			route.targetId,
			route.departJd,
			route.arriveJd,
			route.departureMode,
			route.arrivalMode,
			route.constantThrust ?? '',
			route.lowThrust?.accelMs2 ?? '',
			(route.flybys ?? []).map((flyby) => `${flyby.bodyId}@${flyby.jd}`).join(','),
			originName ?? '',
			targetName ?? ''
		].join('|');
	});

	$effect(() => {
		const key = timelineKey;
		untrack(() => {
			const route = panel.selectedRoute;
			if (key === null || !route) {
				onTimelineChange(null);
				return;
			}
			onTimelineChange(
				buildTimeline(route, (bodyId) => {
					if (bodyId === origin?.id && originName) return originName;
					if (bodyId === target?.id && targetName) return targetName;
					return resolveBodyName(bodyId);
				})
			);
		});
	});

	// Leaving the planner takes its trajectories off the map with it.
	$effect(() => () => onPathChange(null));
	$effect(() => () => onOptionsChange([]));
	$effect(() => () => onTimelineChange(null));

	// One end is enough: exchanging it with an empty one turns "going to Mars"
	// into "leaving Mars", which is how half a trip gets turned round.
	let anyEnd = $derived(originPicked || targetPicked);

	// Where each trajectory the solver found sits on the launch-window field. Only
	// those: a swing-by departs years outside the grid's own span and a drive held
	// all the way is not a point on it at all, so neither has a place to be marked.
	let windowMarks = $derived([
		...panel.routes.map((choice) => ({
			id: choice.profile,
			departJd: choice.route.departJd,
			tofDays: choice.route.tofDays,
			label: routeLabel(choice.profile)
		})),
		...(panel.custom
			? [
					{
						id: 'custom',
						departJd: panel.custom.departJd,
						tofDays: panel.custom.tofDays,
						label: routeLabel('custom')
					}
				]
			: [])
	]);

	// Which of the two steps is showing. A trajectory is chosen or it is not, and
	// that is the whole of it — there is no third state where the form and the
	// trajectory are both up.
	let chosen = $derived(panel.selected);

	// What the arc has instead of a launch window: how long the drive is off in
	// the middle of it. Read beside the trajectory it belongs to, and again over
	// the list when a coast has pushed the arc past the deadline — that is the one
	// term that can take it off the list, so it has to stay reachable to be undone.
	let torchSelected = $derived(chosen?.route.constantThrust != null);
	let coastDays = $derived(
		torchSelected ? (chosen?.route.legs.find((leg) => leg.kind === 'cruise')?.days ?? 0) : 0
	);
	// Against the crossing rather than the whole trip: the two burns and the coast
	// tile it exactly, so the share is what the slider divides. A trip whose
	// arrival is months of aerobraking would read as almost no coast at all.
	let coastShare = $derived.by(() => {
		const crossing = chosen?.route.tofDays ?? 0;
		return crossing > 0 ? coastDays / crossing : 0;
	});

	function swap() {
		// Modes ride along with their end, and every departure mode is also an
		// arrival one — so only the mode coming back needs a fallback, for the
		// three a departure cannot be: a flyby, a capture ellipse, a transfer orbit.
		const previousOriginMode = panel.originMode;
		const previousOriginAlt = panel.originAltKm;
		panel.originMode = ORIGIN_MODES.includes(panel.targetMode) ? panel.targetMode : 'low-orbit';
		panel.targetMode = previousOriginMode;
		panel.originAltKm = panel.targetAltKm;
		panel.targetAltKm = previousOriginAlt;
		onSwap();
	}
</script>

<!--
  What the constant-thrust arc has instead of a launch window, and the same kind
  of choice: the one thing left to pick once the drive has fixed everything else.
  Rendered in two places, because a coast can be what took every route off the
  list and it has to outlive the list to be undone.
-->
{#snippet cruiseTime()}
	<section class="flex flex-col gap-2">
		<div class="flex items-baseline justify-between gap-2">
			<h4 class="text-sm font-medium">{m.travel_cruise_time()}</h4>
			<span class="shrink-0 text-xs tabular-nums">
				{#if !torchSelected}
					<span class="text-muted-foreground">—</span>
				{:else if coastDays > 0}
					<!-- The share is what the slider sets and what compares across trips;
					     the duration is what it means for this one. -->
					{formatPercent(coastShare)}
					<span class="text-muted-foreground ms-1">{formatDurationNarrow(coastDays)}</span>
				{:else}
					<span class="text-muted-foreground">{m.travel_cruise_flat_out()}</span>
				{/if}
			</span>
		</div>
		<div class="border-border/60 border-t"></div>
		<Slider
			type="single"
			value={panel.coastFraction}
			onValueChange={(value: number) => (panel.coastFraction = value)}
			min={0}
			max={1}
			step={0.01}
			aria-label={m.travel_cruise_time()}
		/>
		{#if panel.torchMissedDeadline}
			<p class="text-muted-foreground text-[11px]">{m.travel_cruise_missed()}</p>
		{/if}
	</section>
{/snippet}

<div class="flex flex-col gap-5">
	{#if chosen}
		{@const pass = chosen.route.flybys?.[0] ?? null}
		<!-- The trip's terms are a step behind now, and the header above names the
		     trajectory, so what is left to say is between what and when. The
		     qualifier rides here rather than on the title: it is what tells one
		     trajectory from another, and the title is a plain string. -->
		<div class="flex flex-col gap-0.5">
			{#if originName && targetName}
				<p class="truncate text-sm">
					{originName} → {targetName}{#if chosen.route.constantThrust}<span
							class="text-muted-foreground ms-1.5 text-xs tabular-nums"
							>{formatAcceleration(chosen.route.constantThrust)}</span
						>{:else if pass}<span class="text-muted-foreground ms-1.5 text-xs"
							>{m.travel_via({ body: resolveBodyName(pass.bodyId) })}</span
						>{/if}
				</p>
			{/if}
			<p class="text-muted-foreground text-xs tabular-nums">
				{formatJulianDate(chosen.route.departJd)} → {formatJulianDate(chosen.route.arriveJd)}
			</p>
		</div>

		<!-- Above the detail rather than inside it: everything below is what this
		     trajectory costs, and this is the one term still open to change. -->
		{#if torchSelected}{@render cruiseTime()}{/if}

		{#if originTravel && targetTravel}
			<RouteDetail
				route={chosen.route}
				origin={originTravel}
				target={targetTravel}
				state={panel}
				nameOf={resolveBodyName}
			/>
		{/if}
	{:else}
		<!-- Three rows: origin, connector, destination. The swap sits in the middle
	     row so it stays between the two boxes however tall either one grows. -->
		<div class="grid grid-cols-[1fr_2rem] gap-x-2 gap-y-1.5">
			<div class="col-start-1 row-start-1 min-w-0">
				<EndpointField
					role="origin"
					bodyName={originName}
					placeholder={m.travel_choose_origin()}
					isFeature={panel.originIsFeature}
					mode={panel.originMode}
					onModeChange={(mode: EndpointMode) => (panel.originMode = mode)}
					choices={originChoices}
					customAltKm={panel.originAltKm}
					maxAltKm={originTravel && originFacts
						? maxCustomAltitudeKm(originTravel, originFacts)
						: 0}
					onCustomAlt={(km: number) => (panel.originAltKm = km)}
					priceKms={(choice: OrbitChoice) => priceEnd('origin', choice)}
					open={openField === 'origin'}
					onOpenChange={(next: boolean) => setOpenField('origin', next)}
					excludeIds={excludeForOrigin}
					onPick={(pick) => {
						onOriginChange(pick);
						// A feature has already answered "how"; anything else moves on to it.
						if (pick.featureId !== null) openField = null;
					}}
				/>
			</div>

			<div class="col-start-1 row-start-2">
				<span class="bg-border ms-[18px] block h-2.5 w-px" aria-hidden="true"></span>
			</div>

			<div class="col-start-1 row-start-3 min-w-0">
				<EndpointField
					role="target"
					bodyName={targetName}
					placeholder={m.travel_choose_target()}
					isFeature={panel.targetIsFeature}
					mode={panel.targetMode}
					onModeChange={(mode: EndpointMode) => (panel.targetMode = mode)}
					choices={targetChoices}
					customAltKm={panel.targetAltKm}
					maxAltKm={targetTravel && targetFacts
						? maxCustomAltitudeKm(targetTravel, targetFacts)
						: 0}
					onCustomAlt={(km: number) => (panel.targetAltKm = km)}
					priceKms={(choice: OrbitChoice) => priceEnd('target', choice)}
					open={openField === 'target'}
					onOpenChange={(next: boolean) => setOpenField('target', next)}
					excludeIds={excludeForTarget}
					onPick={(pick) => {
						onTargetChange(pick);
						if (pick.featureId !== null) openField = null;
					}}
				/>
			</div>

			<div class="relative col-start-2 row-start-2">
				<Button
					variant="outline"
					size="icon"
					onclick={swap}
					disabled={!anyEnd}
					class="text-muted-foreground absolute end-0 top-1/2 -translate-y-1/2"
					aria-label={m.travel_swap()}
				>
					<ArrowUpDownIcon />
				</Button>
			</div>
		</div>

		<div class="flex flex-col gap-2">
			<Segmented
				options={TIME_MODES}
				value={panel.timeMode}
				onchange={(mode: TimeMode) => {
					panel.timeMode = mode;
					// Seed the date on the way in, so the mode means something the moment
					// it is chosen rather than after a second click.
					if (mode !== 'now' && panel.pickedJd == null) panel.pickedJd = defaultPickedJd(mode);
				}}
				ariaLabel={m.travel_when()}
			/>
			{#if panel.timeMode !== 'now'}
				<DateField
					label={panel.timeMode === 'depart' ? m.travel_depart_on() : m.travel_arrive_by()}
					jd={panel.pickedJd ?? defaultPickedJd(panel.timeMode)}
					onChange={(jd) => (panel.pickedJd = jd)}
				/>
			{/if}
			{#if nextWindowJd != null}
				<div class="flex items-baseline justify-between gap-2 text-xs">
					<span class="text-muted-foreground min-w-0 truncate">
						{m.travel_next_window({ date: formatJulianDate(nextWindowJd) })}
					</span>
					<button
						type="button"
						class="shrink-0 underline underline-offset-2"
						onclick={() => {
							panel.timeMode = 'depart';
							panel.pickedJd = nextWindowJd;
						}}
					>
						{m.travel_use_window()}
					</button>
				</div>
			{/if}
		</div>

		<div class="flex flex-col gap-2">
			<button
				type="button"
				onclick={() => {
					vehicleOpen = !vehicleOpen;
					// Nothing waits on this — the routes are already solved, and the
					// list fills in when it lands.
					if (vehicleOpen) void panel.loadVehicles();
				}}
				aria-expanded={vehicleOpen}
				class="border-border/60 bg-muted/40 hover:bg-muted flex items-center gap-2 rounded-md border px-2.5 py-2 text-start"
			>
				<RocketIcon class="text-muted-foreground size-4 shrink-0" />
				<span class="min-w-0 flex-1">
					<span class="block truncate text-sm {panel.vehicle ? '' : 'text-muted-foreground'}">
						{panel.vehicle ? vehicleName(panel.vehicle) : m.travel_add_craft()}
					</span>
					<!-- The open list says all this on the chosen row already. -->
					{#if panel.vehicle && !vehicleOpen}
						<VehicleMeta
							vehicle={panel.vehicle}
							route={panel.selectedRoute}
							manifest={panel.manifest}
						/>
					{/if}
				</span>
				<ChevronDownIcon
					class="text-muted-foreground size-4 shrink-0 transition-transform {vehicleOpen
						? 'rotate-180'
						: ''}"
				/>
			</button>

			{#if vehicleOpen}
				{#if shownVehicles.length > 0}
					<!-- The catalogue runs to dozens of craft, so it scrolls in place rather
				     than pushing the routes below it off the panel. -->
					<ScrollArea class="border-border/60 rounded-md border" viewportClasses="max-h-56">
						<ul class="flex flex-col p-1">
							{#each shownVehicles as vehicle (vehicle.id)}
								<!-- Only the chosen craft survives the filter without fitting the
							     departure, so the note reads as "here is why it stopped
							     working", not as a rule on the list. -->
								{@const fits = canDepartFrom(vehicle, panel.departureMode)}
								<!-- Seats only matter once someone is aboard, so the column appears
							     with the first passenger rather than reading "0" against every
							     probe in the catalogue. -->
								{@const seats = panel.passengers > 0 ? crewCapacity(vehicle) : null}
								{@const tooSmall = seats !== null && seats < panel.passengers}
								<li>
									<button
										type="button"
										onclick={() => {
											panel.selectVehicle(vehicle.id);
											vehicleOpen = false;
										}}
										class="hover:bg-muted flex w-full items-start gap-2 rounded-[5px] px-2 py-1.5 text-start text-xs {tooSmall
											? 'opacity-50'
											: ''}"
									>
										<span class="min-w-0 flex-1">
											<span class="flex items-center gap-2">
												<span class="min-w-0 flex-1 truncate {fits ? '' : 'text-muted-foreground'}">
													{vehicleName(vehicle)}
												</span>
												{#if !fits}
													<span class="text-muted-foreground shrink-0 text-[11px]">
														{departureNote(vehicle)}
													</span>
												{/if}
												{#if seats !== null}
													<span
														class="text-muted-foreground flex shrink-0 items-center gap-1 tabular-nums"
														title={m.travel_seats({ value: seats })}
													>
														<UsersIcon class="size-3" />{seats}
													</span>
												{/if}
												{#if panel.vehicleId === vehicle.id}
													<CheckIcon class="size-3.5 shrink-0" />
												{/if}
											</span>
											<VehicleMeta
												{vehicle}
												route={panel.selectedRoute}
												manifest={panel.manifest}
											/>
										</span>
									</button>
								</li>
							{/each}
						</ul>
					</ScrollArea>
				{:else if panel.vehicles.length > 0}
					<p class="text-muted-foreground text-[11px]">{m.travel_no_craft_for_route()}</p>
				{:else}
					<p class="text-muted-foreground text-[11px]">{m.travel_craft_loading()}</p>
				{/if}
			{/if}

			<!-- Beside the craft rather than inside it: what you are taking is a fact
		     about the trip, and it stands on its own before one is chosen — it is
		     what narrows the catalogue down. -->
			<ManifestField
				passengers={panel.passengers}
				payloadKg={panel.payloadKg}
				fit={panel.manifestFit}
				onPassengersChange={(value) => (panel.passengers = value)}
				onPayloadChange={(value) => (panel.payloadKg = value)}
			/>
		</div>

		<!-- A term of the trip rather than of the destination: it does not change
	     where you end up, it changes what getting there costs and how long it
	     takes. So it sits with the craft and the manifest, next to the list of
	     trajectories whose figures it moves. -->
		{#if showAero}
			<div class="flex flex-col gap-1.5">
				<span class="text-muted-foreground text-[10px] uppercase">{m.travel_aero_assist()}</span>
				<Segmented
					options={aeroChoices}
					value={aeroValue}
					onchange={(aero: AeroAssist) => (panel.aero = aero)}
					ariaLabel={m.travel_aero_assist()}
				/>
			</div>
		{/if}

		{#if panel.status === 'blocked'}
			<!-- An end left blank is a prompt, not a failure — no alert icon on it. -->
			{#if panel.blocked === 'no-target'}
				<p class="text-muted-foreground text-xs">{m.travel_no_target()}</p>
			{:else if panel.blocked === 'no-origin'}
				<p class="text-muted-foreground text-xs">{m.travel_no_origin()}</p>
			{:else}
				<p class="text-muted-foreground flex items-start gap-2 text-xs">
					<CircleAlertIcon class="mt-0.5 size-3.5 shrink-0" />
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
		{:else if panel.status === 'empty' && panel.offered.length === 0}
			<p class="text-muted-foreground text-xs">{m.travel_no_routes()}</p>
			<!-- A coast long enough to miss the deadline is what took the arc off the
			     list, so the control that did it has to outlive the list. -->
			{#if panel.torchMissedDeadline}{@render cruiseTime()}{/if}
		{:else if panel.offered.length > 0}
			{#if panel.torchMissedDeadline}{@render cruiseTime()}{/if}
			<RouteList
				state={panel}
				nameOf={resolveBodyName}
				onFocusField={panel.grid ? () => chart?.focusField() : null}
			/>

			{#if panel.grid}
				<!-- The field the list is read off, with the solved routes marked on it:
			     every point on it is a trajectory nobody offered, and picking one adds
			     it to the list rather than opening it — a pick is a drag, and every
			     point crossed on the way would otherwise be opened and closed again. -->
				<section class="flex flex-col gap-2">
					<h4 class="text-sm font-medium">{m.travel_launch_windows()}</h4>
					<div class="border-border/60 border-t"></div>
					<PorkchopChart
						bind:this={chart}
						grid={panel.grid}
						route={panel.custom}
						marks={windowMarks}
						hovered={hoveredProfile}
						onHover={(id) => (hoveredProfile = id)}
						onPick={(departJd, tofDays) => panel.pickCustom(departJd, tofDays)}
					/>
				</section>
			{/if}
		{/if}
	{/if}
</div>
