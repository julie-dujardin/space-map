<!--
  One family of trajectory as one line each: what it is and when it runs on the
  left, what it costs on the right. Picking one is what opens it — this is the
  first of the panel's two steps, and every row here is a way into the second.

  A route the chosen craft cannot fly stays visible and goes quiet, with the
  reason in place of its figures — hiding it would leave the panel silently
  short of options.

  Each family ends with the option placed by hand: a window picked off the
  porkchop, or an arc set by the cruise slider. Both appear before they hold
  anything, so the control below them reads as a choice.

  A swing-by names the body it goes past, since that and its dates are the only
  things separating it from the routes above.
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
		/** What each trajectory puts the craft through. Empty until the scan lands,
		 *  which is a row without a third line rather than a row that is wrong. */
		hazardsFor?: (profile: RouteOption) => readonly Hazard[];
		/** The trajectory being pointed at, from the field below or from its arc on
		 *  the map. */
		hovered?: string | null;
		onHover?: ((id: string | null) => void) | null;
	}
	let {
		state,
		family,
		nameOf = (id: string) => id,
		hazardsFor = () => [],
		hovered = null,
		onHover = null
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
		<li>
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
					class="border-border/60 flex w-full items-center gap-3 rounded-md border px-3 py-2 text-start opacity-50 transition-colors"
				>
					{@render rowBody()}
				</button>
			{:else}
				<!-- The trajectory lands in the URL, so the row is a link. A plain click
				     swaps the step in place. -->
				<a
					href={tripRouteHref(appState, state.trip, choice.profile)}
					class="border-border/60 hover:bg-muted/40 flex w-full items-center gap-3 rounded-md border px-3 py-2 text-start transition-colors"
					onclick={(e) => {
						if (isModifiedClick(e)) return;
						e.preventDefault();
						state.choose(choice.profile);
					}}
				>
					{@render rowBody()}
				</a>
			{/if}
		</li>
	{/each}

	{#if family === 'transfer'}
		<li><WindowBox {state} {hazardsFor} {hovered} {onHover} /></li>
	{/if}

	{#if family === 'constant-thrust'}
		<li><CruiseBox {state} {hazardsFor} /></li>
	{/if}
</ul>
