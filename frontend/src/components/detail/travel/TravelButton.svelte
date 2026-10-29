<!--
  Entry into the trip planner from the drawer's button row. The destination
  is the panel's body, or the primary star of a star system. The departure is
  Earth. The button is hidden when no trip reaches the destination, because an
  entry that leads nowhere is worse than none.
-->
<script lang="ts">
	import { getContext } from 'svelte';
	import { isExtrasolarObjectId } from '$lib/fetch/extrasolar/ids';
	import NavigationIcon from '@lucide/svelte/icons/navigation';
	import { Button } from '$lib/components/ui/button/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import type { BodyData } from '$lib/types/objects';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { isModifiedClick } from '$lib/modified-click';
	import { extrasolarTripTarget, travelEntry } from '$lib/travel/travel-entry';

	interface Props {
		/** The body of the panel. */
		target: BodyData;
		/** Set on a surface feature's panel: the trip ends in that named place,
		 *  which also fixes the arrival to a landing. */
		featureId?: number | null;
	}
	let { target, featureId = null }: Props = $props();

	const ctx = getContext<ContextManager | undefined>('ctx');
	const appState = getContext<AppState | undefined>('appState');

	let targetId = $derived(target.id);
	let away = $derived(isExtrasolarObjectId(targetId));
	/** The star or planet that the planner resolves an extrasolar target to. */
	let awayTarget = $state<BodyData | null>(null);
	$effect(() => {
		const id = targetId;
		awayTarget = null;
		if (!isExtrasolarObjectId(id)) return;
		let cancelled = false;
		void extrasolarTripTarget(id).then((body) => {
			if (!cancelled) awayTarget = body;
		});
		return () => {
			cancelled = true;
		};
	});

	let entry = $derived(
		away
			? awayTarget && travelEntry(ctx, appState, awayTarget)
			: travelEntry(ctx, appState, target, featureId)
	);
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
