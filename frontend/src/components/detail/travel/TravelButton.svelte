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
	import { EARTH_ID } from '$lib/constants';
	import { isModifiedClick, navHref } from '$lib/state/focus-link';
	import { transferPlan } from '$lib/travel/travel-body';

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

	// Nobody travels to where they already are, so Earth's own panel opens with
	// the departure unchosen rather than with no button at all.
	let departure = $derived(target.id === EARTH_ID ? null : EARTH_ID);

	let plannable = $derived.by(() => {
		if (!ctx) return false;
		if (departure === null) return true;
		// Any bucket, not just majors — that used to hide the button on every
		// small body and probe, exactly the ones worth planning a trip to.
		const lookup = (id: string) => ctx.getBody(id)?.data;
		const earth = lookup(EARTH_ID);
		if (!earth) return false;
		return transferPlan(earth, target, lookup).kind !== 'blocked';
	});

	let destination = $derived({ id: target.id, featureId });
	let href = $derived(navHref(appState, departure, destination));
</script>

{#if plannable && href}
	<!-- An anchor, not a button: it navigates, so ⌘-click has to open a real URL. -->
	<Button
		{href}
		variant="secondary"
		size="icon-lg"
		class="rounded-full"
		onclick={(e: MouseEvent) => {
			if (isModifiedClick(e) || !appState) return;
			e.preventDefault();
			appState.setNav(departure, destination);
		}}
	>
		<NavigationIcon />
		<span class="sr-only">{m.travel_open()}</span>
	</Button>
{/if}
