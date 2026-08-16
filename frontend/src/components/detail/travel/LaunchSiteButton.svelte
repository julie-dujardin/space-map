<!--
  A launch site's way into the trip planner.

  The site is the *departure* — it is where things leave from, and a trip to a
  cosmodrome is not what anyone came to this page to plan — so the destination
  is left unchosen for the planner's first step to ask about.

  A range is not a place, so the trip leaves from one of its pads: the busiest,
  named on the box and swappable there. Hidden while the pads are still coming,
  and for good on a range GCAT can place none of.
-->
<script lang="ts">
	import { getContext } from 'svelte';
	import NavigationIcon from '@lucide/svelte/icons/navigation';
	import { Button } from '$lib/components/ui/button/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { EARTH_ID } from '$lib/constants';
	import { isModifiedClick, navHref } from '$lib/state/focus-link';
	import { busiestPad, fetchLaunchPads, type LaunchPad } from '$lib/travel/launch-pad';

	interface Props {
		/** The `site-` collection this page is. */
		slug: string;
	}
	let { slug }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');

	let pad = $state<LaunchPad | null>(null);
	$effect(() => {
		const wanted = slug;
		pad = null;
		void fetchLaunchPads(wanted).then((pads) => {
			if (wanted === slug) pad = busiestPad(pads);
		});
	});

	// Every launch site in the catalogue is on Earth, and a pad is a point on
	// whatever body holds it — so the body is named here rather than looked up.
	let departure = $derived(
		pad
			? {
					id: EARTH_ID,
					featureId: null,
					place: { latDeg: pad.latDeg, lonDeg: pad.lonDeg, siteSlug: slug }
				}
			: null
	);
	let href = $derived(departure ? navHref(appState, departure, null) : undefined);
</script>

{#if departure && href}
	<!-- An anchor, not a button: it navigates, so ⌘-click has to open a real URL. -->
	<Button
		{href}
		variant="secondary"
		size="icon-lg"
		class="rounded-full"
		onclick={(e: MouseEvent) => {
			if (isModifiedClick(e) || !appState) return;
			e.preventDefault();
			appState.setNav(departure, null);
		}}
	>
		<NavigationIcon />
		<span class="sr-only">{m.travel_launch_from_here()}</span>
	</Button>
{/if}
