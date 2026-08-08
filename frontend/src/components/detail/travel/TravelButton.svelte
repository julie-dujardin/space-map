<!--
  The object panel's way into the trip planner, in the drawer's button row.

  The body whose panel it sits in becomes the destination — the panel answers
  "how do I get here" — with the departure left at the default. Hidden rather
  than disabled when no trip is possible (Earth to itself, or a moon of the
  departure body's own primary): an entry point that always dead-ends is worse
  than no entry point.
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
	import { sameSystemBlock } from '$lib/travel/travel-body';

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

	let plannable = $derived.by(() => {
		if (!ctx || target.id === EARTH_ID) return false;
		// Whatever bucket a body sits in — majors, a zone, a spacecraft group.
		// Reading only the majors index used to hide the button on every small body
		// and probe, which are exactly the ones worth planning a trip to.
		const lookup = (id: string) => ctx.getBody(id)?.data;
		const earth = lookup(EARTH_ID);
		if (!earth) return false;
		return sameSystemBlock(earth, target, lookup) === null;
	});

	let destination = $derived({ id: target.id, featureId });
	let href = $derived(navHref(appState, EARTH_ID, destination));
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
			appState.setNav(EARTH_ID, destination);
		}}
	>
		<NavigationIcon />
		<span class="sr-only">{m.travel_open()}</span>
	</Button>
{/if}
