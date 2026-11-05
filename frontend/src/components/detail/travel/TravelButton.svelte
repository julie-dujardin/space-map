<!--
  Entry into the trip planner from the drawer's button row. The destination
  is the panel's body, or the primary star of a star system. The departure is
  Earth. The button is hidden when no trip reaches the destination, because an
  entry that leads nowhere is worse than none.
-->
<script lang="ts">
	import NavigationIcon from '@lucide/svelte/icons/navigation';
	import { getContext } from 'svelte';
	import { Button } from '$lib/components/ui/button/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import type { BodyData } from '$lib/types/objects';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { isModifiedClick } from '$lib/modified-click';
	import { TripEntry } from '$lib/travel/trip-entry.svelte';

	interface Props {
		/** The body of the panel. */
		target: BodyData;
		/** Set on a surface feature's panel: the trip ends in that named place,
		 *  which also fixes the arrival to a landing. */
		featureId?: number | null;
	}
	let { target, featureId = null }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const trip = new TripEntry(
		() => target,
		() => featureId
	);
	let entry = $derived(trip.entry);
</script>

{#if entry}
	<!-- An anchor, not a button: it navigates, so ⌘-click has to open a real URL. -->
	<Button
		href={entry.href}
		variant="secondary"
		size="icon-lg"
		class="rounded-full"
		onclick={(e: MouseEvent) => {
			if (isModifiedClick(e) || !appState || !entry) return;
			e.preventDefault();
			appState.setNav(entry.departure, entry.destination);
		}}
	>
		<NavigationIcon />
		<span class="sr-only">{m.travel_open()}</span>
	</Button>
{/if}
