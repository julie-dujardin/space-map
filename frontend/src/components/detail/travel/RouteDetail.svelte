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
	import {
		dvWithPayloadKms,
		routeDurationDays,
		type LegKind,
		type Route,
		type TravelBody
	} from '$lib/math/travel';
	import { returnDvKms, signalDelaySeconds } from '$lib/travel/arrival-stats';
	import { formatDurationNarrow, SECONDS_PER_DAY } from '$lib/format/duration';
	import {
		dvParts,
		formatAcceleration,
		formatDv,
		formatSpeed,
		lightPercent
	} from '$lib/travel/format';
	import type { TravelPanelState } from '$lib/travel/panel.svelte';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import DeltaVLadder from './DeltaVLadder.svelte';
	import { legLabel } from './leg-labels';

	interface Props {
		route: Route;
		origin: TravelBody;
		target: TravelBody;
		state: TravelPanelState;
	}
	let { route, origin, target, state }: Props = $props();

	const ICONS: Record<LegKind, typeof RocketIcon> = {
		ascent: ArrowUpIcon,
		injection: RocketIcon,
		cruise: MoveRightIcon,
		boost: ChevronsRightIcon,
		brake: ChevronsLeftIcon,
		assist: WavesIcon,
		capture: OrbitIcon,
		aerobrake: WindIcon,
		descent: ArrowDownIcon
	};

	// Speed at the flip, which is what the accelerating half of the arc bought.
	let topSpeedKms = $derived(route.legs.find((leg) => leg.kind === 'boost')?.dvKms ?? 0);
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
			: { label: m.travel_launch_c3(), value: route.c3Km2S2.toFixed(1), unit: m.travel_km2_s2() }
	]);

	let delay = $derived(signalDelaySeconds(origin, target, route.arriveJd));

	// A launcher's job ends at injection, so it has no Δv of its own left for
	// arrival — that belongs to whatever it threw. A craft with no published
	// engine has no Δv to subtract either, which is a different silence: the
	// row says so rather than showing a figure nobody measured. Cargo is already
	// off the top, so loading the hold shortens the return this row prices.
	let remaining = $derived.by(() => {
		const vehicle = state.vehicle;
		if (!vehicle || vehicle.kind === 'launcher') return null;
		if (vehicle.unlimitedDv) return Infinity;
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
	let returnCost = $derived(returnDvKms(target, route));
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
			{#each route.legs as leg, i (i)}
				{@const Icon = ICONS[leg.kind]}
				<li class="flex gap-3">
					<div class="flex flex-col items-center">
						<span
							class="border-border/60 bg-background text-muted-foreground flex size-6 shrink-0 items-center justify-center rounded-full border"
						>
							<Icon class="size-3" />
						</span>
						{#if i < route.legs.length - 1}
							<span class="bg-border/60 w-px flex-1"></span>
						{/if}
					</div>
					<div class="min-w-0 flex-1 pb-3">
						<div class="flex items-baseline justify-between gap-2">
							<span class="truncate text-sm">{legLabel(leg.kind)}</span>
							<span class="shrink-0 text-sm tabular-nums">
								{leg.dvKms > 0 ? formatDv(leg.dvKms) : formatDurationNarrow(leg.days)}
							</span>
						</div>
						<!-- A burn costs Δv, a coast costs time, and a leg under thrust
						     costs both — the figure above is the Δv, so the duration is
						     said here rather than lost, with the acceleration that was
						     held for it. -->
						{#if leg.dvKms > 0 && leg.days > 0}
							<span class="text-muted-foreground text-xs">
								{route.constantThrust
									? m.travel_burn_at({
											duration: formatDurationNarrow(leg.days),
											value: formatAcceleration(route.constantThrust)
										})
									: formatDurationNarrow(leg.days)}
							</span>
						{/if}
						<!-- The campaign's own step already says what it is; the note
						     belongs on the burns the air made smaller, and it names which
						     of the two manoeuvres made them smaller. -->
						{#if leg.kind === 'aerobrake'}
							<span class="text-muted-foreground text-xs">{m.travel_aero_campaign()}</span>
						{:else if leg.aerobraked}
							<span class="text-muted-foreground text-xs">
								{route.aero === 'aerocapture' ? m.travel_aerocaptured() : m.travel_aerobraked()}
							</span>
						{/if}
					</div>
				</li>
			{/each}
		</ol>
	</section>
</div>
