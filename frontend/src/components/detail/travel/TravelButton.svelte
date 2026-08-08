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
	}
	let { target }: Props = $props();

	const ctx = getContext<ContextManager | undefined>('ctx');
	const appState = getContext<AppState | undefined>('appState');

	let plannable = $derived.by(() => {
		if (!ctx || target.id === EARTH_ID) return false;
		const bodies = new Map<string, BodyData>();
		for (const [id, b] of ctx.bodies.bodiesById) bodies.set(id, b.data);
		const earth = bodies.get(EARTH_ID);
		if (!earth) return false;
		return sameSystemBlock(earth, target, bodies) === null;
	});

	let href = $derived(navHref(appState, EARTH_ID, target.id));
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
			appState.setNav(EARTH_ID, target.id);
		}}
	>
		<NavigationIcon />
		<span class="sr-only">{m.travel_open()}</span>
	</Button>
{/if}
