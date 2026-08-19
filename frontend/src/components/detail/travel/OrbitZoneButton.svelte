<!--
  An Earth-orbit zone's way into the trip planner.

  The zone is the *destination* — Earth, met in the orbit the zone is made of —
  and the departure stays unchosen for the next step: where a trip to low orbit
  leaves from is the question the page can't answer. Zones the planner holds no
  orbit in have no button at all.
-->
<script lang="ts">
	import { getContext } from 'svelte';
	import NavigationIcon from '@lucide/svelte/icons/navigation';
	import { Button } from '$lib/components/ui/button/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { EARTH_ID } from '$lib/constants';
	import { isModifiedClick, navHref } from '$lib/state/focus-link';
	import { orbitZoneTarget } from '$lib/travel/orbit-zone-target';

	interface Props {
		/** The `class-` zone this page is. */
		slug: string;
	}
	let { slug }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');

	let target = $derived(orbitZoneTarget(slug));
	// The shape rides along only for the custom orbit, which is the one that means
	// anything by it; the plane only for a zone that is one. A zone naming no far
	// end is met on a circular orbit, so both ends take the one altitude.
	let terms = $derived(
		target
			? {
					targetMode: target.mode,
					...(target.altKm
						? { targetAltKm: target.altKm, targetApoAltKm: target.apoAltKm ?? target.altKm }
						: {}),
					...(target.incDeg === undefined ? {} : { targetIncDeg: target.incDeg })
				}
			: undefined
	);
	let href = $derived(terms ? navHref(appState, null, EARTH_ID, terms) : undefined);
</script>

{#if terms && href}
	<!-- An anchor, not a button: it navigates, so ⌘-click has to open a real URL. -->
	<Button
		{href}
		variant="secondary"
		size="icon-lg"
		class="rounded-full"
		onclick={(e: MouseEvent) => {
			if (isModifiedClick(e) || !appState) return;
			e.preventDefault();
			appState.setNav(null, EARTH_ID, terms);
		}}
	>
		<NavigationIcon />
		<span class="sr-only">{m.travel_to_orbit_zone()}</span>
	</Button>
{/if}
