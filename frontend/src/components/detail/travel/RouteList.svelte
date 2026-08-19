<!--
  One family's trajectories, a line each: what and when on the left, cost on
  the right. Picking a row opens the panel's second step.

  A route the craft cannot fly stays visible and blocked, with the reason in
  place of its figures, rather than silently disappearing.

  The by-hand option (porkchop window or cruise slider) is shown before it
  holds a trajectory, so the control below still reads as a choice.
-->
<script lang="ts">
	import { getContext } from 'svelte';
	import type { OfferedRoute, TravelPanelState } from '$lib/travel/panel.svelte';
	import { routesIn, type RouteFamily } from '$lib/travel/route-families';
	import type { RouteOption } from '$lib/travel/trip';
	import type { Hazard } from '$lib/travel/hazards';
	import { blockedText } from './route-blocked';
	import { isModifiedClick, tripRouteHref } from '$lib/state/focus-link';
	import type { AppState } from '$lib/state/app-state.svelte';
	import RouteRowBody from './RouteRowBody.svelte';
	import CruiseBox from './CruiseBox.svelte';
	import WindowBox from './WindowBox.svelte';

	const appState = getContext<AppState | undefined>('appState');

	interface Props {
		state: TravelPanelState;
		/** Which family is being read; the tabs above choose it. */
		family: RouteFamily | null;
		/** What to call the body a swing-by passes. */
		nameOf?: (id: string) => string;
		/** What each trajectory puts the craft through; empty until the scan lands. */
		hazardsFor?: (profile: RouteOption) => readonly Hazard[];
		/** The trajectory being pointed at, from the field below or from its arc on
		 *  the map. */
		hovered?: string | null;
		onHover?: ((id: string | null) => void) | null;
		/** When the next transfer window opens, for the field that window is read
		 *  off. Null when the two ends have no alignment to wait for. */
		nextWindowJd?: number | null;
		onUseWindow?: ((jd: number) => void) | null;
	}
	let {
		state,
		family,
		nameOf = (id: string) => id,
		hazardsFor = () => [],
		hovered = null,
		onHover = null,
		nextWindowJd = null,
		onUseWindow = null
	}: Props = $props();

	/** A trajectory placed by hand belongs to the box at the end of its family,
	 *  next to the control that places it. */
	const BY_HAND: readonly RouteOption[] = ['custom', 'constant-thrust-custom'];

	let shown = $derived(
		routesIn(state.offered, family).filter((choice) => !BY_HAND.includes(choice.profile))
	);

	/** The body a route goes past, named, or null when it goes straight there. */
	function via(choice: OfferedRoute): string | null {
		const pass = choice.route.flybys?.[0];
		return pass ? nameOf(pass.bodyId) : null;
	}
</script>

<ul class="flex flex-col gap-2">
	{#each shown as choice (choice.profile)}
		{@const blocked = blockedText(state, choice.route)}
		{@const lit = hovered === choice.profile}
		<!-- Hover rides the row's box, not the control in it: a blocked row is a
		     disabled button, which swallows pointer events. -->
		<li
			onpointerenter={() => onHover?.(choice.profile)}
			onpointerleave={() => {
				if (hovered === choice.profile) onHover?.(null);
			}}
		>
			{#snippet rowBody()}
				<RouteRowBody
					profile={choice.profile}
					route={choice.route}
					hazards={hazardsFor(choice.profile)}
					{blocked}
					via={via(choice)}
				/>
			{/snippet}
			{#if blocked}
				<button
					type="button"
					disabled
					class="border-border/60 block w-full rounded-md border px-3 py-2 text-start opacity-50 transition-colors {lit
						? 'bg-muted/40'
						: ''}"
				>
					{@render rowBody()}
				</button>
			{:else}
				<!-- The trajectory lands in the URL, so the row is a link. A plain click
				     swaps the step in place. -->
				<a
					href={tripRouteHref(appState, state.trip, choice.profile)}
					class="border-border/60 hover:bg-muted/40 block w-full rounded-md border px-3 py-2 text-start transition-colors {lit
						? 'bg-muted/40'
						: ''}"
					onclick={(e) => {
						if (isModifiedClick(e)) return;
						e.preventDefault();
						state.choose(choice.profile);
					}}
					onfocus={() => onHover?.(choice.profile)}
					onblur={() => {
						if (hovered === choice.profile) onHover?.(null);
					}}
				>
					{@render rowBody()}
				</a>
			{/if}
		</li>
	{/each}

	{#if family === 'transfer'}
		<li><WindowBox {state} {hazardsFor} {hovered} {onHover} {nextWindowJd} {onUseWindow} /></li>
	{/if}

	{#if family === 'constant-thrust'}
		<li><CruiseBox {state} {hazardsFor} /></li>
	{/if}
</ul>
