<!--
  The planets of a star, from the file of its planetary system, then the
  other stars of that system that have planets.
-->
<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import Section from '../sections/kit/Section.svelte';
	import MemberRow from './MemberRow.svelte';
	import PlanetRows from './PlanetRows.svelte';
	import { extrasolarObjectId } from '$lib/fetch/extrasolar/ids';
	import type { PlanetSystem } from '$lib/fetch/extrasolar/planets';
	import { localName } from '$lib/format/name';
	import { targetClick, targetHref, type LinkTarget } from '$lib/state/focus-link';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusFeature, FocusObject } from '$lib/state/focusable';

	interface Props {
		system: PlanetSystem;
		/** The star whose planets lead the list. */
		hostId: number;
		/** Lists the other hosts of the file. A page that lists the stars of its
		 *  system needs no such list. */
		others?: boolean;
	}

	let { system, hostId, others = true }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');
	const focusFeature = getContext<FocusFeature | undefined>('focusFeature');
	let nav = $derived({ appState, focusObject, focusFeature });

	let planets = $derived(system.planets.filter((p) => p.host === hostId));
	let otherHosts = $derived(
		others ? system.hosts.filter((h) => h.id !== hostId && h.planets.length > 0) : []
	);

	function link(target: LinkTarget, name: string) {
		return { href: targetHref(appState, target, name), onclick: targetClick(nav, target, name) };
	}
</script>

{#snippet planetRows()}
	<PlanetRows {planets} />
{/snippet}

{#snippet hostRows()}
	<ul class="flex flex-col">
		{#each otherHosts as host (host.id)}
			{@const name = localName(host) ?? String(host.id)}
			<MemberRow {name} {...link({ id: extrasolarObjectId(host.id) }, name)}>
				<span class="text-muted-foreground">
					{m.exoplanet_planet_count({ count: host.planets.length })}
				</span>
			</MemberRow>
		{/each}
	</ul>
{/snippet}

{#if planets.length > 0}
	<Section
		title={m.exoplanet_strip_planets()}
		titleMeta={String(planets.length)}
		header={planetRows}
	/>
{/if}
{#if otherHosts.length > 0}
	<Section title={m.exoplanet_strip_other_hosts()} header={hostRows} />
{/if}
