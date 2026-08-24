<!--
  Everything about the chosen route: the headline figures, the Δv budget, what
  you are left with on arrival, and the steps in order.
-->
<script lang="ts">
	import Link from '../sections/kit/Link.svelte';
	import * as m from '$lib/paraglide/messages.js';
	import RocketIcon from '@lucide/svelte/icons/rocket';
	import ArrowUpIcon from '@lucide/svelte/icons/arrow-up';
	import ArrowDownIcon from '@lucide/svelte/icons/arrow-down';
	import FlameIcon from '@lucide/svelte/icons/flame';
	import HandshakeIcon from '@lucide/svelte/icons/handshake';
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
		formatDvBrief,
		formatEndOrbit,
		formatSpeed,
		lightPercent
	} from '$lib/travel/format';
	import { formatNumber } from '$lib/format/quantities';
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
	import CraftSpecs from './CraftSpecs.svelte';
	import DeltaVLadder from './DeltaVLadder.svelte';
	import { craftSpecs, craftSpecSources } from './craft-specs';
	import { radiationSources } from '$lib/credits/radiation-sources';
	import { legLabel } from './leg-labels';
	import { hazardIcon, HAZARD_TEXT } from './hazard-style';

	interface Props {
		route: Route;
		origin: TravelBody;
		target: TravelBody;
		state: TravelPanelState;
		/** What to call the body a swing-by passes — it is neither end of the trip,
		 *  so nothing else here knows its name. */
		nameOf?: (id: string) => string;
		/** What the trip's origin is called, passed rather than looked up through
		 *  `nameOf` — that only knows bodies *between* the two ends and hands back
		 *  the raw id for either of them. */
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

	// The craft only qualifies a hazard here, never in the list: a row there
	// states where the trip goes and shouldn't change because a craft was
	// picked — least of all before a linked one has even fetched.
	let shownHazards = $derived(adjustForVehicle(hazards, state.vehicle, route));
	// The id is the last resort rather than the first: it is at least unambiguous,
	// where a blank would leave a sentence with a hole in it.
	let originLabel = $derived(originName ?? nameOf(route.departureId));

	/** Under this the pass is free in every sense that matters: metres per second
	 *  against a budget in kilometres. */
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
		rendezvous: HandshakeIcon,
		'aero-pass': FlameIcon,
		aerobrake: WindIcon,
		raise: OrbitIcon,
		descent: ArrowDownIcon
	};

	// Fastest the craft goes, reported by the arc rather than the ladder: once
	// gravity is in the crossing, spent Δv no longer equals bought speed. Falls
	// back to the burn for a route solved before that was true.
	let topSpeedKms = $derived(
		route.peakSpeedKms ?? route.legs.find((leg) => leg.kind === 'boost')?.dvKms ?? 0
	);
	let topSpeedPercentC = $derived(lightPercent(topSpeedKms));

	// Launch energy is the third figure for a thrown arc; a drive held all the
	// way leaves at exactly escape speed, so C3 zero says nothing — top speed does.
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
			: {
					label: m.travel_top_speed(),
					value: formatNumber(topSpeedKms),
					unit: m.symbol_kilometre_per_second()
				}
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
				? // A spiral is thrown by nothing, so it has no launch energy — what
					// it has instead is the acceleration the whole trip follows from.
					{ label: m.travel_drive_accel(), ...accelerationParts(route.lowThrust.accelMs2) }
				: {
						label: m.travel_launch_c3(),
						value: formatNumber(route.c3Km2S2),
						unit: m.travel_km2_s2()
					}
	]);

	let delay = $derived(signalDelaySeconds(origin, target, route.arriveJd));

	// A launcher's Δv ends at injection — arrival belongs to whatever it threw.
	// An unpublished engine has no Δv to subtract either, a different silence
	// from a real zero. A craft the route can't be judged against (an ion
	// drive's budget against a Lambert arc's) gets no figure at all: the two
	// aren't the same quantity.
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
	// A craft whose propellant was never a constraint has nothing to report and
	// nothing missing either, so it's answered before the unpublished-engine
	// silence — which would be a strange thing to say about a torch drive.
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

	// The legs, bracketed by the orbits at either end where those ends are orbits
	// — nothing spent, no time passed, but the legs alone don't say where the
	// trip starts and stops. A launch or landing already says that itself, so
	// neither gets one.
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
			// A burn costs Δv, a coast costs time, a leg under thrust costs both — so
			// the duration goes here rather than being lost, with the held acceleration.
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
			// The aero steps say what they are in their own names; the note that a
			// leg was aerobraked belongs only on the one still wearing an engine
			// name — the direct entry's descent.
			if (leg.kind === 'aerobrake') notes.push(m.travel_aero_campaign());
			else if (leg.kind === 'aero-pass') notes.push(m.travel_aero_absorbed());
			else if (leg.aerobraked) {
				notes.push(route.aero === 'aerocapture' ? m.travel_aerocaptured() : m.travel_aerobraked());
			}
			list.push({
				key: `${index}:${leg.kind}`,
				kind: leg.kind,
				// The pass's figure is what the atmosphere removed — the step costs
				// nothing, and that is the number that says why.
				figure:
					leg.kind === 'aero-pass' && leg.absorbedKms
						? formatDv(leg.absorbedKms)
						: leg.dvKms > 0
							? formatDv(leg.dvKms)
							: formatDurationNarrow(leg.days),
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

	// The craft's own figures, and the works behind them — drawn apart, since the
	// citations belong at the foot of the panel rather than mid-way down it.
	let specs = $derived(state.vehicle ? craftSpecs(state.vehicle, route) : []);
	// The dose figures are computed here rather than fetched, so their works come
	// from a module of their own; the craft's come with the catalogue.
	let sources = $derived([...craftSpecSources(specs), ...radiationSources(shownHazards)]);

	// What the detour bought, against the best the direct search found — the
	// reason this route is listed at all, so it's said rather than left to be
	// worked out from two ladder rows.
	let saving = $derived.by(() => {
		if (!pass || state.routes.length === 0) return null;
		const cheapest = Math.min(...state.routes.map((choice) => choice.route.totalDvKms));
		const saved = cheapest - route.totalDvKms;
		return saved > 0 ? saved : null;
	});
</script>

{#snippet statTile(tile: Tile, props: Record<string, unknown>)}
	<!-- A tile with a tooltip is a real button, so the explanation the tooltip
	     carries can be reached by focus, not only by pointer. -->
	<svelte:element
		this={tile.tooltip ? 'button' : 'div'}
		type={tile.tooltip ? 'button' : undefined}
		class="border-border/60 bg-muted/40 flex flex-col gap-1 rounded-md border p-2.5 text-start {tile.tooltip
			? 'cursor-help'
			: ''}"
		{...props}
	>
		<div class="text-muted-foreground text-[10px] uppercase">{tile.label}</div>
		<div class="text-lg leading-tight font-semibold tabular-nums">
			{tile.value}{#if tile.unit}<span class="text-muted-foreground ms-1 text-[10px] font-normal"
					>{tile.unit}</span
				>{/if}
		</div>
	</svelte:element>
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

	<!-- Above the budget because it is where the budget's figures come from: the
	     craft was chosen a step back and is off screen by the time this is read. -->
	{#if state.vehicle}
		<CraftSpecs vehicle={state.vehicle} {specs} />
	{/if}

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
		<!-- The pass is the whole reason for this route, and none of it shows in the
		     ladder: a working assist costs nothing, so the interesting figures are
		     the geometry, not the Δv. -->
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
						{m.travel_assist_saves({ value: formatDvBrief(saving) })}
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
					{formatNumber(pass.turnDeg)}°
					{#if pass.dvKms < FREE_PASS_KMS}
						<span class="text-muted-foreground ms-1 text-xs">{m.travel_flyby_free()}</span>
					{/if}
				</dd>
			</dl>
		</section>
	{/if}

	{#if shownHazards.length > 0}
		<!-- What the trajectory puts the craft through — the half of the choice the
		     Δv ladder can't show, since two routes at the same budget can be very
		     different trips. -->
		<section class="flex flex-col gap-2">
			<h4 class="text-sm font-medium">{m.travel_hazards()}</h4>
			<div class="border-border/60 border-t"></div>
			<ul class="flex flex-col gap-3">
				{#each shownHazards as hazard (hazard.kind)}
					{@const Icon = hazardIcon(hazard)}
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
							<!-- Said the way the rest of the panel says a date: a stretch gets
							     both ends, a moment gets the one it is. Severity comes from the
							     icon's colour, not a word. -->
							<div class="text-muted-foreground text-xs tabular-nums">
								{#if hazard.endJd > hazard.startJd}
									{formatJulianDate(hazard.startJd)}
									<MoveRightIcon
										class="inline size-[1em] align-[-0.125em] rtl:rotate-180"
										aria-hidden="true"
									/>
									{formatJulianDate(hazard.endJd)}
								{:else}
									{formatJulianDate(hazard.startJd)}
								{/if}
							</div>
							<p class="text-muted-foreground mt-1 text-xs">
								{hazardDetail(hazard, originLabel, hazard.bodyId ? nameOf(hazard.bodyId) : '')}
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
						{m.travel_return_needs({ value: formatDvBrief(returnCost) })}
					</span>
				{:else if remaining >= returnCost}
					<span class="text-sm">{m.travel_return_possible()}</span>
				{:else}
					<span class="text-sm">{m.travel_return_one_way()}</span>
					<span class="text-muted-foreground text-xs">
						{m.travel_return_needs({ value: formatDvBrief(returnCost) })}
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
							<Icon class="size-3" aria-hidden="true" />
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

	{#if sources.length > 0}
		<!-- One per line, each giving up its tail to the ellipsis: titles run to a
		     catalogue name and report number, and together would read as one
		     citation with commas. Same shape as an object's sources footer. -->
		<div class="text-muted-foreground text-xs/5">
			<span>{m.travel_spec_sources()}</span>
			{#each sources as source (source.url)}
				<div class="flex">
					<Link href={source.url} external icon={false} title={source.title} class="truncate"
						>{source.title}</Link
					>
				</div>
			{/each}
		</div>
	{/if}
</div>
