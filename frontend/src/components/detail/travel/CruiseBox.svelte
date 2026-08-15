<!--
  The arc set by hand, and the slider that sets it. Comes last in the family and
  is dashed, like the window picked off the porkchop.

  The row keeps its height with no arc behind it, so the slider does not move
  while you drag it. The box also stays when the arc is gone: a long coast can
  miss the deadline, and the reader needs the slider back to undo that.
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

	/** The handle's width, from the slider's own `size-3`. The handle is held
	 *  inside the bar, so a mark on the same span must be held the same way. */
	const THUMB_PX = 12;
</script>

<section class="border-border/60 flex flex-col rounded-md border border-dashed">
	{#if route && !blocked}
		<!-- The trajectory lands in the URL, so the row is a link. A plain click
		     swaps the step in place. -->
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
					<!-- The share compares across trips. The duration says what it means
					     for this one, and a flat-out crossing has none. -->
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
			<!-- Where the named arcs sit on the same span, each in the colour of its
			     own row. Drawn behind the bar and the handle, so it shows above and
			     below them and nothing it marks is covered. -->
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
