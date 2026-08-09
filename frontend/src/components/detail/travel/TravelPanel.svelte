<!--
  The travel panel: describe a trip, get trajectories.

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
		buildTrajectoryPath,
		canDepartFrom,
		checkFeasibility,
		crewCapacity,
		hohmannTransferDays,
		nextTransferWindows,
		systemArcBounds,
		type AeroAssist,
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
		type TransferPlan
	} from '$lib/travel/travel-body';
	import { TravelPanelState, type BlockReason } from '$lib/travel/panel.svelte';
	import {
		serializeTripSuffix,
		type EndpointMode,
		type TimeMode,
		type TripState
	} from '$lib/travel/trip';
	import type { TravelEndpointPick } from '$lib/travel/endpoint';
	import { buildTimeline, type TimelineEntry } from '$lib/travel/timeline';
	import { departureNote, vehicleName } from './vehicle-labels';
	import { Button } from '$lib/components/ui/button/index.js';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import Segmented from './Segmented.svelte';
	import VehicleMeta from './VehicleMeta.svelte';
	import DateField from './DateField.svelte';
	import ManifestField from './ManifestField.svelte';
	import EndpointField from './EndpointField.svelte';
	import RouteList from './RouteList.svelte';
	import RouteDetail from './RouteDetail.svelte';
	import PorkchopChart from './PorkchopChart.svelte';

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
		/** The trajectory being read, as geometry for the map to draw. Null
		 *  whenever there is nothing to show. */
		onPathChange: (path: TrajectoryPath | null) => void;
		/** The same trajectory as the legs it is made of, for the timeline along the
		 *  bottom of the map. */
		onTimelineChange: (entries: TimelineEntry[] | null) => void;
		/** What a body passed on the way is called. The two ends name themselves;
		 *  this is for the ones in between. */
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
	// Aerobraking walks a loose orbit down into a tight one, so it is only on
	// offer when a tight one is what was asked for.
	let aeroChoices = $derived([
		{ value: 'none' as const, label: m.travel_aero_none() },
		{
			value: 'aerocapture' as const,
			label: isLanding ? m.travel_aero_direct_entry() : m.travel_aero_aerocapture()
		},
		...(panel.targetMode === 'low-orbit'
			? [{ value: 'aerobraking' as const, label: m.travel_aero_aerobraking() }]
			: [])
	]);
	// A trip that was aerobraking and is now landing is not braking on the way in
	// at all until it says so again.
	let aeroValue = $derived(
		panel.aero === 'aerobraking' && panel.targetMode !== 'low-orbit' ? 'none' : panel.aero
	);

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
			: hohmannTransferDays(originTravel, targetTravel, frame.centralMu);
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

	// The constant-thrust arc is its own effect: it turns on the craft, which the
	// solve above deliberately ignores — a different ship is not a different
	// search — and it answers without a worker, so it costs nothing to redo.
	$effect(() => {
		const from = originTravel;
		const to = targetTravel;
		if (block || !from || !to) {
			panel.torch = null;
			return;
		}
		panel.updateTorch(from, to, nowJd, frame);
	});

	$effect(() => () => panel.dispose());

	// What the map is drawing, and what would change it. The solve effect above
	// re-runs several times a second, handing back a fresh (and usually identical)
	// route object each time; rebuilding a few hundred propagated points off every
	// one of those would be work nobody asked for. So the geometry is keyed on
	// what actually shapes it, and only a change in the key rebuilds.
	let pathKey = $derived.by(() => {
		const route = panel.selectedRoute;
		if (!route || !plan || !origin || !target) return null;
		const centerId = transferCenterId(plan, origin, target, lookup);
		if (!centerId) return null;
		const via = route.flybys?.[0];
		return [
			centerId,
			route.departureId,
			route.targetId,
			route.departJd,
			route.tofDays,
			route.departureMode,
			route.arrivalMode,
			route.constantThrust ?? '',
			via ? `${via.bodyId}@${via.jd}` : '',
			frame.systemPrimary ?? '',
			frame.centralMu ?? ''
		].join('|');
	});

	// One effect owns the drawn path, the way one owns the solve. Everything it
	// reads beyond the key is untracked, so a route object replaced with an equal
	// one cannot get the geometry rebuilt behind the key's back.
	$effect(() => {
		const key = pathKey;
		untrack(() => {
			if (key === null) {
				onPathChange(null);
				return;
			}
			const route = panel.selectedRoute;
			const centerId =
				plan && origin && target ? transferCenterId(plan, origin, target, lookup) : null;
			if (!route || !centerId || !originTravel || !targetTravel) {
				onPathChange(null);
				return;
			}
			const path = buildTrajectoryPath(originTravel, targetTravel, route, {
				centerId,
				centralMu: frame.centralMu,
				systemPrimary: frame.systemPrimary
			});
			if (!path) {
				console.debug(
					`[travel] no drawable path for ${route.departureId} → ${route.targetId} ` +
						`(depart ${route.departJd}, ${route.tofDays} d)`
				);
			}
			onPathChange(path);
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

	// Leaving the planner takes its trajectory off the map with it.
	$effect(() => () => onPathChange(null));
	$effect(() => () => onTimelineChange(null));

	// One end is enough: exchanging it with an empty one turns "going to Mars"
	// into "leaving Mars", which is how half a trip gets turned round.
	// The field belongs to the trajectories that are read off it. A
	// constant-thrust arc is not a point on it — every departure date flies the
	// same one — so choosing that arc puts the whole launch-window section away,
	// the picker for a hand-picked window with it.
	let windowGrid = $derived(panel.selectedRoute?.constantThrust ? null : panel.grid);

	let anyEnd = $derived(originPicked || targetPicked);

	function swap() {
		// Modes ride along with their end. Only the destination can be a flyby, so
		// a flyby arrival lands on the nearest departure that means something.
		const previousOriginMode = panel.originMode;
		// Only a destination can be flown past or held in a loose ellipse; both
		// fall back to the parking orbit a departure actually leaves from.
		panel.originMode = panel.targetMode === 'surface' ? 'surface' : 'low-orbit';
		panel.targetMode = previousOriginMode;
		onSwap();
	}
</script>

<div class="flex flex-col gap-5">
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
				open={openField === 'origin'}
				onToggle={() => (openField = openField === 'origin' ? null : 'origin')}
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
				open={openField === 'target'}
				onToggle={() => (openField = openField === 'target' ? null : 'target')}
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
										<VehicleMeta {vehicle} route={panel.selectedRoute} manifest={panel.manifest} />
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
	{:else if panel.offered.length > 0}
		<RouteList state={panel} onFocusField={windowGrid ? () => chart?.focusField() : null} />

		{#if windowGrid}
			<!-- Sits with the list rather than the detail: it is about which route
			     to pick, not about the one already picked. -->
			<section class="flex flex-col gap-2">
				<h4 class="text-sm font-medium">{m.travel_launch_windows()}</h4>
				<div class="border-border/60 border-t"></div>
				<PorkchopChart
					bind:this={chart}
					grid={windowGrid}
					route={panel.selectedRoute}
					onPick={(departJd, tofDays) => panel.pickCustom(departJd, tofDays)}
				/>
			</section>
		{/if}

		{#if panel.selectedRoute && originTravel && targetTravel}
			<RouteDetail
				route={panel.selectedRoute}
				origin={originTravel}
				target={targetTravel}
				state={panel}
			/>
		{/if}
	{/if}
</div>
