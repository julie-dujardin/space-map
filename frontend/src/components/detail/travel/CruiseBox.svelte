<!--
  The arc set by hand; comes last in the family, dashed like the porkchop
  window. The row keeps its height even with no arc, so the slider doesn't
  jump while dragged, and stays visible when a missed deadline clears the arc
  so the reader can recover.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { getContext } from 'svelte';
	import { Slider } from '$lib/components/ui/slider/index.js';
	import { formatDurationNarrow } from '$lib/format/duration';
	import { formatPercent } from '$lib/format/quantities';
	import type { TravelPanelState } from '$lib/travel/panel.svelte';
	import type { Hazard } from '$lib/travel/hazards';
	import type { RouteOption } from '$lib/travel/trip';
	import { isModifiedClick, tripRouteHref } from '$lib/state/focus-link';
	import type { AppState } from '$lib/state/app-state.svelte';
	import RouteRowBody from './RouteRowBody.svelte';
	import { blockedText } from './route-blocked';
	import { TORCH_PRESETS } from '$lib/travel/torch-arcs';
	import { routeMark } from './route-tier';

	const appState = getContext<AppState | undefined>('appState');

	interface Props {
		state: TravelPanelState;
		hazardsFor?: (profile: RouteOption) => readonly Hazard[];
	}
	let { state, hazardsFor = () => [] }: Props = $props();

	const PROFILE: RouteOption = 'constant-thrust-custom';

	let route = $derived(state.torchCustom?.route ?? null);
	let blocked = $derived(route ? blockedText(state, route) : null);
	let coastDays = $derived(route?.legs.find((leg) => leg.kind === 'cruise')?.days ?? 0);
	// Measured against the crossing, which the burns and the coast fill exactly.
	// Months of aerobraking at the end would hide the coast.
	let coastShare = $derived.by(() => {
		const crossing = route?.tofDays ?? 0;
		return crossing > 0 ? coastDays / crossing : 0;
	});

	let rowClass =
		'flex w-full items-center gap-3 rounded-md px-3 pt-2 pb-1 text-start transition-colors';

	/** Slider handle width, from its own `size-3` — marks on the same span must match it. */
	const THUMB_PX = 12;
</script>

<section class="border-border/60 flex flex-col rounded-md border border-dashed">
	{#if route && !blocked}
		<!-- The trajectory lands in the URL, so the row is a link; a plain click swaps the step in place. -->
		<a
			href={tripRouteHref(appState, state.trip, PROFILE)}
			class="hover:bg-muted/40 {rowClass}"
			onclick={(e) => {
				if (isModifiedClick(e)) return;
				e.preventDefault();
				state.choose(PROFILE);
			}}
		>
			<RouteRowBody profile={PROFILE} {route} hazards={hazardsFor(PROFILE)} reserveHazards />
		</a>
	{:else}
		<div class={rowClass} class:opacity-50={blocked !== null}>
			<RouteRowBody profile={PROFILE} {route} {blocked} reserveHazards />
		</div>
	{/if}
	<div class="flex flex-col gap-2 px-3 pt-1 pb-2">
		<div class="flex items-baseline justify-between gap-2">
			<h4 class="text-muted-foreground text-xs">{m.travel_cruise_time()}</h4>
			<span class="shrink-0 text-xs tabular-nums">
				{#if route}
					<!-- Share compares across trips; duration says what it means for this one. -->
					{formatPercent(coastShare)}
					{#if coastDays > 0}
						<span class="text-muted-foreground ms-1">{formatDurationNarrow(coastDays)}</span>
					{/if}
				{:else}
					<span class="text-muted-foreground">&mdash;</span>
				{/if}
			</span>
		</div>
		<div class="relative">
			<!-- Named-arc marks on the same span, coloured per row. Drawn behind the
			     bar and handle so nothing covers them. -->
			<span class="pointer-events-none absolute inset-0 block" aria-hidden="true">
				{#each TORCH_PRESETS as preset (preset.profile)}
					<span
						class="absolute top-1/2 h-5 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-full {routeMark(
							preset.profile
						)}"
						style="inset-inline-start: calc({THUMB_PX /
							2}px + {preset.coastFraction} * (100% - {THUMB_PX}px))"
					></span>
				{/each}
			</span>
			<Slider
				type="single"
				value={state.coastFraction}
				onValueChange={(value: number) => (state.coastFraction = value)}
				min={0}
				max={1}
				step={0.01}
				aria-label={m.travel_cruise_time()}
			/>
		</div>
		{#if state.torchMissedDeadline}
			<p class="text-muted-foreground text-xs">{m.travel_cruise_missed()}</p>
		{/if}
	</div>
</section>
