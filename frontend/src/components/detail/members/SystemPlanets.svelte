<!--
  The planets of a star system's node, one group per host. The only host of a
  list needs no heading on its own page.
-->
<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import Link from '../sections/kit/Link.svelte';
	import Section from '../sections/kit/Section.svelte';
	import PlanetRows from './PlanetRows.svelte';
	import { extrasolarObjectId } from '$lib/fetch/extrasolar/ids';
	import { targetClick, targetHref } from '$lib/state/focus-link';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusFeature, FocusObject } from '$lib/state/focusable';
	import type { SystemHost } from '$lib/state/star-system';

	interface Props {
		hosts: SystemHost[];
		/** The ID of the page. */
		pageId: number;
	}

	let { hosts, pageId }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');
	const focusFeature = getContext<FocusFeature | undefined>('focusFeature');
	let nav = $derived({ appState, focusObject, focusFeature });

	let count = $derived(hosts.reduce((sum, host) => sum + host.planets.length, 0));
	let headed = $derived(hosts.length > 1 || hosts[0]?.id !== pageId);
</script>

{#snippet groups()}
	<div class="flex flex-col gap-2">
		{#each hosts as host (host.id)}
			{@const target = { id: extrasolarObjectId(host.id) }}
			<div class="flex flex-col">
				{#if headed}
					<h4 class="pt-2 text-sm font-medium">
						<Link
							href={targetHref(appState, target, host.name)}
							onclick={targetClick(nav, target, host.name)}
							variant="heading">{host.name}</Link
						>
					</h4>
				{/if}
				<PlanetRows planets={host.planets} />
			</div>
		{/each}
	</div>
{/snippet}

{#if count > 0}
	<Section title={m.exoplanet_strip_planets()} titleMeta={String(count)} header={groups} />
{/if}
