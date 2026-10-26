<!--
  The planets of a star, from the file of its planetary system, then the
  other stars of that system that have planets. On a planet's page the
  planet itself is the row with no link.
-->
<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import Section from '../sections/kit/Section.svelte';
	import MemberRow from './MemberRow.svelte';
	import { extrasolarObjectId, planetObjectId } from '$lib/fetch/extrasolar/ids';
	import type { Planet, PlanetSystem } from '$lib/fetch/extrasolar/planets';
	import { formatUnit, sigFigures } from '$lib/format/quantities';
	import { formatDays } from '../sections/planet/planet-rows';
	import { targetClick, targetHref, type LinkTarget } from '$lib/state/focus-link';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusFeature, FocusObject } from '$lib/state/focusable';

	interface Props {
		system: PlanetSystem;
		/** The star whose planets lead the list. */
		hostId: number;
		/** The number of the planet whose page this is. */
		current?: number;
	}

	let { system, hostId, current }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');
	const focusFeature = getContext<FocusFeature | undefined>('focusFeature');
	let nav = $derived({ appState, focusObject, focusFeature });

	// From the star outward; a planet with no orbit goes last.
	let planets = $derived(
		system.planets
			.filter((p) => p.host === hostId)
			.sort((a, b) => (axis(a) ?? Infinity) - (axis(b) ?? Infinity) || a.number - b.number)
	);
	let others = $derived(system.hosts.filter((h) => h.id !== hostId && h.planets.length > 0));

	function figure(planet: Planet, name: string): number | null {
		const value = planet.values[name];
		return typeof value === 'number' ? value : null;
	}

	function axis(planet: Planet): number | null {
		return figure(planet, 'semi_major_axis');
	}

	function link(target: LinkTarget, name: string) {
		return { href: targetHref(appState, target, name), onclick: targetClick(nav, target, name) };
	}
</script>

{#snippet planetRows()}
	<ul class="flex flex-col">
		{#each planets as planet (planet.number)}
			{@const a = figure(planet, 'semi_major_axis')}
			{@const period = figure(planet, 'period')}
			<MemberRow
				name={planet.name}
				tile={planet.letter ?? String(planet.number)}
				aria-current={planet.number === current ? 'page' : undefined}
				{...planet.number === current
					? {}
					: link({ id: planetObjectId(planet.host, planet.number) }, planet.name)}
				valuesClass="tabular-nums"
			>
				<span>
					{a === null ? '–' : `${sigFigures(a, 3)}\u00a0${formatUnit('astronomical_unit', true)}`}
				</span>
				{#if period !== null}
					<span class="text-muted-foreground">{formatDays(period)}</span>
				{/if}
			</MemberRow>
		{/each}
	</ul>
{/snippet}

{#snippet hostRows()}
	<ul class="flex flex-col">
		{#each others as host (host.id)}
			{@const name = host.name ?? String(host.id)}
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
{#if others.length > 0}
	<Section title={m.exoplanet_strip_other_hosts()} header={hostRows} />
{/if}
