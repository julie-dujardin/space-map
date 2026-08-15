<!--
  The window picked by hand, and the field it is picked off. Comes last in the
  family and is dashed, like the arc set by the cruise slider.

  The row keeps its height with no window behind it, so the field does not move
  when one is picked. With no window it says where one comes from, and gives the
  focus to the field.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { getContext } from 'svelte';
	import type { TravelPanelState } from '$lib/travel/panel.svelte';
	import type { Hazard } from '$lib/travel/hazards';
	import type { RouteOption } from '$lib/travel/trip';
	import { isModifiedClick, tripRouteHref } from '$lib/state/focus-link';
	import type { AppState } from '$lib/state/app-state.svelte';
	import PorkchopChart from './PorkchopChart.svelte';
	import RouteRowBody from './RouteRowBody.svelte';
	import { blockedText } from './route-blocked';
	import { routeLabel } from './route-labels';
	import { routeMark } from './route-tier';

	const appState = getContext<AppState | undefined>('appState');

	interface Props {
		state: TravelPanelState;
		/** The trajectory being pointed at, from here or from its arc on the map. */
		hovered?: string | null;
		onHover?: ((id: string | null) => void) | null;
		hazardsFor?: (profile: RouteOption) => readonly Hazard[];
	}
	// Renamed on the way in: a local called `state` would read as the rune.
	let { state: panel, hovered = null, onHover = null, hazardsFor = () => [] }: Props = $props();

	const PROFILE: RouteOption = 'custom';

	let chart = $state<ReturnType<typeof PorkchopChart> | null>(null);

	let route = $derived(panel.custom);
	let blocked = $derived(route ? blockedText(panel, route) : null);

	// Where each solved window sits on the field, each in the colour of its row.
	// Only these: a swing-by departs years outside the grid's own span and a drive
	// held all the way is not a point on it at all.
	let marks = $derived([
		...panel.routes.map((choice) => ({
			id: choice.profile,
			departJd: choice.route.departJd,
			tofDays: choice.route.tofDays,
			label: routeLabel(choice.profile),
			mark: routeMark(choice.profile)
		})),
		...(route
			? [
					{
						id: PROFILE,
						departJd: route.departJd,
						tofDays: route.tofDays,
						label: routeLabel(PROFILE),
						mark: routeMark(PROFILE)
					}
				]
			: [])
	]);

	let rowClass =
		'flex w-full items-center gap-3 rounded-md px-3 pt-2 pb-1 text-start transition-colors';
</script>

<!-- The box is the field: without one there is nothing to pick off. -->
{#if panel.grid}
	<section class="border-border/60 flex flex-col rounded-md border border-dashed">
		{#if route && !blocked}
			<!-- The trajectory lands in the URL, so the row is a link. A plain click
		     swaps the step in place. -->
			<a
				href={tripRouteHref(appState, panel.trip, PROFILE)}
				class="hover:bg-muted/40 {rowClass}"
				onclick={(e) => {
					if (isModifiedClick(e)) return;
					e.preventDefault();
					panel.choose(PROFILE);
				}}
			>
				<RouteRowBody profile={PROFILE} {route} hazards={hazardsFor(PROFILE)} reserveHazards />
			</a>
		{:else if route}
			<div class="opacity-50 {rowClass}">
				<RouteRowBody profile={PROFILE} {route} {blocked} reserveHazards />
			</div>
		{:else}
			<button
				type="button"
				class="hover:bg-muted/40 {rowClass}"
				onclick={() => chart?.focusField()}
			>
				<RouteRowBody
					profile={PROFILE}
					route={null}
					hint={m.travel_windows_pick_prompt()}
					reserveHazards
				/>
			</button>
		{/if}
		<div class="flex flex-col gap-2 px-3 pt-1 pb-2">
			<h4 class="text-muted-foreground text-xs">{m.travel_launch_windows()}</h4>
			<!-- Every point on the field is a trajectory nobody offered. Picking one adds
		     it to the list rather than opening it: a pick is a drag, and every point
		     crossed on the way would otherwise be opened and closed again. -->
			<PorkchopChart
				bind:this={chart}
				grid={panel.grid}
				{route}
				{marks}
				{hovered}
				onHover={(id) => onHover?.(id)}
				onPick={(departJd, tofDays) => panel.pickCustom(departJd, tofDays)}
			/>
		</div>
	</section>
{/if}
