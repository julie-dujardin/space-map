<!--
  Entry into the trip planner from the drawer's button row. The panel's body
  becomes the destination; departure defaults to Earth. Hidden rather than
  disabled when the destination has no orbit to travel: a dead-end entry
  point is worse than none.
-->
<script lang="ts">
	import { getContext } from 'svelte';
	import NavigationIcon from '@lucide/svelte/icons/navigation';
	import { Button } from '$lib/components/ui/button/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import type { BodyData } from '$lib/types/objects';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { isModifiedClick } from '$lib/modified-click';
	import { travelEntry } from '$lib/travel/travel-entry';

	interface Props {
		/** The body whose panel this sits in — the destination. */
		target: BodyData;
		/** Set on a surface feature's panel: the trip ends in that named place,
		 *  which also fixes the arrival to a landing. */
		featureId?: number | null;
	}
	let { target, featureId = null }: Props = $props();

	const ctx = getContext<ContextManager | undefined>('ctx');
	const appState = getContext<AppState | undefined>('appState');

	let entry = $derived(travelEntry(ctx, appState, target, featureId));
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
