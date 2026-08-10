<!--
  Everything about the chosen route: the headline figures, the Δv budget, what
  you are left with on arrival, and the steps in order.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import RocketIcon from '@lucide/svelte/icons/rocket';
	import ArrowUpIcon from '@lucide/svelte/icons/arrow-up';
	import ArrowDownIcon from '@lucide/svelte/icons/arrow-down';
	import OrbitIcon from '@lucide/svelte/icons/orbit';
	import WindIcon from '@lucide/svelte/icons/wind';
	import MoveRightIcon from '@lucide/svelte/icons/move-right';
	import ChevronsRightIcon from '@lucide/svelte/icons/chevrons-right';
	import ChevronsLeftIcon from '@lucide/svelte/icons/chevrons-left';
	import WavesIcon from '@lucide/svelte/icons/waves';
	import TornadoIcon from '@lucide/svelte/icons/tornado';
	import ShellIcon from '@lucide/svelte/icons/shell';
	import CircleDashedIcon from '@lucide/svelte/icons/circle-dashed';
	import {
		endArrivalOrbit,
		endDepartureOrbit,
		dvWithPayloadKms,
		routeDurationDays,
		type Route,
		type TravelBody
	} from '$lib/math/travel';
	import type { TimelineKind } from '$lib/travel/timeline';
	import { returnDvKms, signalDelaySeconds } from '$lib/travel/arrival-stats';
	import { formatJulianDate } from '$lib/format/date';
	import { formatKm } from '$lib/format/distance';
	import { formatDurationNarrow, SECONDS_PER_DAY } from '$lib/format/duration';
	import {
		accelerationParts,
		dvParts,
		formatAcceleration,
		formatDv,
		formatEndOrbit,
		formatSpeed,
		lightPercent
	} from '$lib/travel/format';
	import type { TravelPanelState } from '$lib/travel/panel.svelte';
	import { adjustForVehicle, type Hazard } from '$lib/travel/hazards';
	import {
		hazardCampaign,
		hazardCraftNote,
		hazardDetail,
		hazardName,
		hazardValue
	} from '$lib/travel/hazard-labels';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import DeltaVLadder from './DeltaVLadder.svelte';
	import { legLabel } from './leg-labels';
	import { HAZARD_ICONS, HAZARD_TEXT } from './hazard-style';

	interface Props {
		route: Route;
		origin: TravelBody;
		target: TravelBody;
		state: TravelPanelState;
		/** What to call the body a swing-by passes — it is neither end of the trip,
		 *  so nothing else here knows its name. */
		nameOf?: (id: string) => string;
		/** What the trip's own origin is called. Passed rather than looked up
		 *  through `nameOf`, which only knows the bodies *between* the two ends —
		 *  asking it for one of them hands back the raw id. */
		originName?: string | null;
		/** What this trajectory puts the craft through. */
		hazards?: readonly Hazard[];
	}
	let {
		route,
		origin,
		target,
		state,
		nameOf = (id: string) => id,
		originName = null,
		hazards = []
	}: Props = $props();

	// The craft only ever qualifies a hazard here, never in the list: a row there
	// is a statement about where the trip goes, and should not change because a
	// craft was picked — least of all in the window before a linked one is fetched.
	let shownHazards = $derived(adjustForVehicle(hazards, state.vehicle, route));
	// The id is the last resort rather than the first: it is at least unambiguous,
	// where a blank would leave a sentence with a hole in it.
	let originLabel = $derived(originName ?? nameOf(route.departureId));

	/** Under this the pass is free in every sense that matters: metres per second
	 *  against a budget in kilometres, and the search only stopped there because
	 *  its last refinement step did. */
	const FREE_PASS_KMS = 0.02;

	// One pass for now; the solver builds no route with two.
	let pass = $derived(route.flybys?.[0] ?? null);

	const ICONS: Record<TimelineKind, typeof RocketIcon> = {
		'start-orbit': CircleDashedIcon,
		'final-orbit': CircleDashedIcon,
		ascent: ArrowUpIcon,
		injection: RocketIcon,
		cruise: MoveRightIcon,
		boost: ChevronsRightIcon,
		brake: ChevronsLeftIcon,
		assist: WavesIcon,
		'powered-cruise': ShellIcon,
		'spiral-out': TornadoIcon,
		'spiral-in': TornadoIcon,
		capture: OrbitIcon,
		aerobrake: WindIcon,
		descent: ArrowDownIcon
	};

	// Fastest the craft goes, which the arc reports rather than the ladder: once
	// gravity is in the crossing the Δv a burn spent is no longer the speed it
	// bought. Falls back to the burn for a route solved before that was true.
	let topSpeedKms = $derived(
		route.peakSpeedKms ?? route.legs.find((leg) => leg.kind === 'boost')?.dvKms ?? 0
	);
	let topSpeedPercentC = $derived(lightPercent(topSpeedKms));

	// Launch energy is the third figure for an arc that is thrown; a drive held
	// all the way leaves at exactly escape speed and C3 zero says nothing about
	// it. How fast it ends up going does.
	interface Tile {
		label: string;
		value: string;
		unit: string;
		/** Spells out a unit too terse to stand alone, like "% c". */
		tooltip?: string;
	}

	let topSpeedTile = $derived<Tile>(
		topSpeedPercentC !== null
			? {
					label: m.travel_top_speed(),
					value: topSpeedPercentC,
					unit: m.travel_percent_c(),
					tooltip: m.travel_percent_c_name()
				}
			: { label: m.travel_top_speed(), value: topSpeedKms.toFixed(0), unit: m.travel_km_s() }
	);
	let tiles = $derived<Tile[]>([
		// The whole trip, not just the transfer: a route that arrives sooner and
		// then aerobrakes for five months is not the faster one.
		{
			label: m.travel_trip_time(),
			value: formatDurationNarrow(routeDurationDays(route)),
			unit: ''
		},
		{ label: m.travel_total_dv(), ...dvParts(route.totalDvKms) },
		route.constantThrust
			? topSpeedTile
			: route.lowThrust
				? // A spiral is thrown by nothing, so it has no launch energy either —
					// and what it does have is the figure the whole trip follows from:
					// years of crossing because the drive pushes at this.
					{ label: m.travel_drive_accel(), ...accelerationParts(route.lowThrust.accelMs2) }
				: { label: m.travel_launch_c3(), value: route.c3Km2S2.toFixed(1), unit: m.travel_km2_s2() }
	]);

	let delay = $derived(signalDelaySeconds(origin, target, route.arriveJd));

	// A launcher's job ends at injection, so it has no Δv of its own left for
	// arrival — that belongs to whatever it threw. A craft with no published
	// engine has no Δv to subtract either, which is a different silence: the
	// row says so rather than showing a figure nobody measured. Cargo is already
	// off the top, so loading the hold shortens the return this row prices.
	//
	// And a craft the route cannot be judged against gets no figure at all: an
	// ion drive's budget minus a Lambert arc's is a subtraction of two things
	// that are not the same quantity, whatever the list above has already said.
	let remaining = $derived.by(() => {
		const vehicle = state.vehicle;
		if (!vehicle || vehicle.kind === 'launcher') return null;
		if (vehicle.unlimitedDv) return Infinity;
		const judged = state.feasibility(route)?.status;
		if (judged === 'not-modelled' || judged === 'unknown') return null;
		const loaded = dvWithPayloadKms(vehicle, state.payloadKg);
		if (loaded === undefined) return null;
		return loaded - route.inSpaceDvKms;
	});
	// A craft whose propellant the work never made a constraint has nothing left
	// over to report and nothing missing either, so it is answered before the
	// silence about an unpublished engine — which would otherwise be a strange
	// thing to say about a torch drive, whose engine is the only published thing.
	let unlimitedDv = $derived(state.vehicle?.unlimitedDv === true);
	let unpublishedDv = $derived(
		!unlimitedDv &&
			state.vehicle !== null &&
			state.vehicle.kind !== 'launcher' &&
			state.vehicle.dvKms === undefined
	);
	let returnCost = $derived(returnDvKms(target, route, state.targetOrbit));

	/** A row of the itinerary: what happens, what it costs, and whatever the
	 *  figure on the right cannot say on its own. */
	interface Step {
		key: string;
		kind: TimelineKind;
		/** Δv, a duration, or the height an end orbit is flown at. */
		figure: string;
		notes: string[];
	}

	// The legs, bracketed by the orbits at either end where those ends are orbits.
	// An orbit is not a leg — nothing is spent and no time passes — but it is where
	// the trip starts and stops, which the legs alone never say. A launch and a
	// landing say it themselves, so neither gets one.
	let steps = $derived.by<Step[]>(() => {
		const list: Step[] = [];
		const start = endDepartureOrbit(origin, route.departureMode, route.departureOrbit);
		if (start) {
			list.push({
				key: 'start-orbit',
				kind: 'start-orbit',
				figure: formatEndOrbit(start, origin.radiusKm),
				notes: []
			});
		}

		for (const [index, leg] of route.legs.entries()) {
			const notes: string[] = [];
			// A burn costs Δv, a coast costs time, and a leg under thrust costs both —
			// the figure is the Δv, so the duration is said here rather than lost, with
			// the acceleration that was held for it.
			if (leg.dvKms > 0 && leg.days > 0) {
				notes.push(
					route.constantThrust
						? m.travel_burn_at({
								duration: formatDurationNarrow(leg.days),
								value: formatAcceleration(route.constantThrust)
							})
						: formatDurationNarrow(leg.days)
				);
			}
			// The campaign's own step already says what it is; the note belongs on the
			// burns the air made smaller, and it names which of the two manoeuvres
			// made them smaller.
			if (leg.kind === 'aerobrake') notes.push(m.travel_aero_campaign());
			else if (leg.aerobraked) {
				notes.push(route.aero === 'aerocapture' ? m.travel_aerocaptured() : m.travel_aerobraked());
			}
			list.push({
				key: `${index}:${leg.kind}`,
				kind: leg.kind,
				figure: leg.dvKms > 0 ? formatDv(leg.dvKms) : formatDurationNarrow(leg.days),
				notes
			});
		}

		const final = endArrivalOrbit(target, route.arrivalMode, route.targetOrbit);
		if (final) {
			list.push({
				key: 'final-orbit',
				kind: 'final-orbit',
				figure: formatEndOrbit(final, target.radiusKm),
				notes: []
			});
		}
		return list;
	});

	// What the detour bought, against the best the direct search found. The saving
	// is the reason this route is on the list at all, so it is said rather than
	// left to be worked out from two rows of the ladder.
	let saving = $derived.by(() => {
		if (!pass || state.routes.length === 0) return null;
		const cheapest = Math.min(...state.routes.map((choice) => choice.route.totalDvKms));
		const saved = cheapest - route.totalDvKms;
		return saved > 0 ? saved : null;
	});
</script>

{#snippet statTile(tile: Tile, props: Record<string, unknown>)}
	<div
		class="border-border/60 bg-muted/40 flex flex-col gap-1 rounded-md border p-2.5 {tile.tooltip
			? 'cursor-help'
			: ''}"
		{...props}
	>
		<div class="text-muted-foreground text-[10px] uppercase">{tile.label}</div>
		<div class="text-lg leading-tight font-semibold tabular-nums">
			{tile.value}{#if tile.unit}<span class="text-muted-foreground ml-1 text-[10px] font-normal"
					>{tile.unit}</span
				>{/if}
		</div>
	</div>
{/snippet}

<div class="flex flex-col gap-4">
	<div class="grid auto-cols-fr grid-flow-col gap-2">
		{#each tiles as tile (tile.label)}
			{#if tile.tooltip}
				<Tooltip.Root>
					<Tooltip.Trigger>
						{#snippet child({ props })}{@render statTile(tile, props)}{/snippet}
					</Tooltip.Trigger>
					<Tooltip.Content>{tile.tooltip}</Tooltip.Content>
				</Tooltip.Root>
			{:else}
				{@render statTile(tile, {})}
			{/if}
		{/each}
	</div>

	<section class="flex flex-col gap-2">
		<div class="flex items-baseline justify-between">
			<h4 class="text-sm font-medium">{m.travel_dv_budget()}</h4>
			<span class="text-muted-foreground text-xs tabular-nums">
				{m.travel_in_space({ value: formatDv(route.inSpaceDvKms) })}
			</span>
		</div>
		<div class="border-border/60 border-t"></div>
		<DeltaVLadder legs={route.legs} />
	</section>

	{#if pass}
		<!-- The pass is the whole reason for the route, and none of it shows in the
		     ladder: an assist that works costs nothing, so the interesting figures
		     are the geometry rather than the Δv. -->
		<section class="flex flex-col gap-2">
			<div class="flex items-baseline justify-between gap-2">
				<h4 class="min-w-0 truncate text-sm font-medium">
					{m.travel_flyby_heading()}
					<span class="text-muted-foreground font-normal"
						>{m.travel_via({ body: nameOf(pass.bodyId) })}</span
					>
				</h4>
				{#if saving !== null}
					<span class="text-muted-foreground shrink-0 text-xs tabular-nums">
						{m.travel_assist_saves({ value: saving.toFixed(1) })}
					</span>
				{/if}
			</div>
			<div class="border-border/60 border-t"></div>
			<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
				<dt class="text-muted-foreground">{m.travel_flyby_closest()}</dt>
				<dd class="text-end tabular-nums">{formatJulianDate(pass.jd)}</dd>

				<dt class="text-muted-foreground">{m.travel_flyby_altitude()}</dt>
				<dd class="text-end tabular-nums">{formatKm(pass.altitudeKm)}</dd>

				<dt class="text-muted-foreground">{m.travel_flyby_turn()}</dt>
				<dd class="text-end tabular-nums">
					{pass.turnDeg.toFixed(0)}°
					{#if pass.dvKms < FREE_PASS_KMS}
						<span class="text-muted-foreground ms-1 text-xs">{m.travel_flyby_free()}</span>
					{/if}
				</dd>
			</dl>
		</section>
	{/if}

	{#if shownHazards.length > 0}
		<!-- What the trajectory puts the craft through, which is the half of the
		     choice the Δv ladder above cannot show: two routes for the same budget
		     can be very different trips. -->
		<section class="flex flex-col gap-2">
			<h4 class="text-sm font-medium">{m.travel_hazards()}</h4>
			<div class="border-border/60 border-t"></div>
			<ul class="flex flex-col gap-3">
				{#each shownHazards as hazard (hazard.kind)}
					{@const Icon = HAZARD_ICONS[hazard.kind]}
					{@const campaign = hazardCampaign(hazard)}
					{@const craftNote = hazardCraftNote(hazard)}
					<li class="flex gap-3">
						<Icon
							class="mt-0.5 size-4 shrink-0 {HAZARD_TEXT[hazard.severity]}"
							aria-hidden="true"
						/>
						<div class="min-w-0 flex-1">
							<div class="flex items-baseline justify-between gap-2">
								<span class="truncate text-sm">{hazardName(hazard.kind)}</span>
								<span class="shrink-0 text-sm tabular-nums">{hazardValue(hazard)}</span>
							</div>
							<!-- When it happens, said the way the rest of the panel says a date:
							     a stretch gets both ends, a moment gets the one it is. How bad it
							     is comes off the icon's colour rather than a word for it. -->
							<div class="text-muted-foreground text-xs tabular-nums">
								{#if hazard.endJd > hazard.startJd}
									{formatJulianDate(hazard.startJd)} → {formatJulianDate(hazard.endJd)}
								{:else}
									{formatJulianDate(hazard.startJd)}
								{/if}
							</div>
							<p class="text-muted-foreground mt-1 text-xs">
								{hazardDetail(hazard, originLabel)}
								{#if campaign}{campaign}{/if}
							</p>
							{#if craftNote}
								<p class="text-muted-foreground mt-1 text-xs">{craftNote}</p>
							{/if}
						</div>
					</li>
				{/each}
			</ul>
		</section>
	{/if}

	<!-- What you are left with once you get there — the questions the budget
	     above cannot answer on its own. -->
	<section class="flex flex-col gap-2">
		<h4 class="text-sm font-medium">{m.travel_on_arrival()}</h4>
		<div class="border-border/60 border-t"></div>
		<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
			<dt class="text-muted-foreground">{m.travel_arrival_speed()}</dt>
			<dd class="text-end tabular-nums">
				{#if lightPercent(route.vInfArrKms) !== null}
					<Tooltip.Root>
						<Tooltip.Trigger class="cursor-help">{formatSpeed(route.vInfArrKms)}</Tooltip.Trigger>
						<Tooltip.Content>{m.travel_percent_c_name()}</Tooltip.Content>
					</Tooltip.Root>
				{:else}
					{formatSpeed(route.vInfArrKms)}
				{/if}
			</dd>

			<!-- What the heat shield sees, which is the arrival speed plus everything
			     the body's own gravity adds on the way down to the pass. -->
			{#if route.entrySpeedKms !== undefined}
				<dt class="text-muted-foreground">{m.travel_entry_speed()}</dt>
				<dd class="text-end tabular-nums">{formatDv(route.entrySpeedKms)}</dd>
			{/if}

			<dt class="text-muted-foreground">{m.travel_signal_delay()}</dt>
			<dd class="text-end tabular-nums">
				{delay == null ? '—' : formatDurationNarrow(delay / SECONDS_PER_DAY)}
			</dd>

			<dt class="text-muted-foreground">{m.travel_dv_remaining()}</dt>
			<dd class="text-end">
				{#if unlimitedDv}
					<span class="text-sm">{m.travel_dv_unlimited()}</span>
				{:else if remaining != null}
					<span class="tabular-nums">{formatDv(remaining)}</span>
				{:else if unpublishedDv}
					<span class="text-muted-foreground text-xs">{m.travel_dv_unpublished()}</span>
				{:else if state.vehicle}
					<span class="text-muted-foreground text-xs">{m.travel_set_by_payload()}</span>
				{:else}
					<span class="text-muted-foreground text-xs">{m.travel_pick_craft()}</span>
				{/if}
			</dd>

			<dt class="text-muted-foreground">{m.travel_return_trip()}</dt>
			<dd class="text-end">
				{#if remaining == null}
					<span class="text-muted-foreground text-xs">
						{m.travel_return_needs({ value: returnCost.toFixed(1) })}
					</span>
				{:else if remaining >= returnCost}
					<span class="text-sm">{m.travel_return_possible()}</span>
				{:else}
					<span class="text-sm">{m.travel_return_one_way()}</span>
					<span class="text-muted-foreground text-xs">
						{m.travel_return_needs({ value: returnCost.toFixed(1) })}
					</span>
				{/if}
			</dd>
		</dl>
	</section>

	<section class="flex flex-col gap-2">
		<h4 class="text-sm font-medium">{m.travel_steps()}</h4>
		<div class="border-border/60 border-t"></div>
		<ol class="flex flex-col">
			{#each steps as step, i (step.key)}
				{@const Icon = ICONS[step.kind]}
				<li class="flex gap-3">
					<div class="flex flex-col items-center">
						<span
							class="border-border/60 bg-background text-muted-foreground flex size-6 shrink-0 items-center justify-center rounded-full border"
						>
							<Icon class="size-3" />
						</span>
						{#if i < steps.length - 1}
							<span class="bg-border/60 w-px flex-1"></span>
						{/if}
					</div>
					<div class="min-w-0 flex-1 pb-3">
						<div class="flex items-baseline justify-between gap-2">
							<span class="truncate text-sm">{legLabel(step.kind)}</span>
							<span class="shrink-0 text-sm tabular-nums">{step.figure}</span>
						</div>
						{#each step.notes as note (note)}
							<span class="text-muted-foreground text-xs">{note}</span>
						{/each}
					</div>
				</li>
			{/each}
		</ol>
	</section>
</div>
