<!-- The planets of a star, from the star outward. A planet with no orbit goes last. -->
<script lang="ts">
	import { getContext } from 'svelte';
	import MemberRow from './MemberRow.svelte';
	import { planetObjectId } from '$lib/fetch/extrasolar/ids';
	import type { Planet } from '$lib/fetch/extrasolar/planets';
	import { formatUnit, sigFigures } from '$lib/format/quantities';
	import { localName } from '$lib/format/name';
	import { formatDays } from '../sections/planet/planet-rows';
	import { targetClick, targetHref } from '$lib/state/focus-link';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusFeature, FocusObject } from '$lib/state/focusable';

	interface Props {
		planets: readonly Planet[];
	}

	let { planets }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');
	const focusFeature = getContext<FocusFeature | undefined>('focusFeature');
	let nav = $derived({ appState, focusObject, focusFeature });

	let ordered = $derived(
		[...planets].sort(
			(a, b) => (axis(a) ?? Infinity) - (axis(b) ?? Infinity) || a.number - b.number
		)
	);

	function figure(planet: Planet, name: string): number | null {
		const value = planet.values[name];
		return typeof value === 'number' ? value : null;
	}

	function axis(planet: Planet): number | null {
		return figure(planet, 'semi_major_axis');
	}

	function link(planet: Planet, name: string) {
		const target = { id: planetObjectId(planet.host, planet.number) };
		return { href: targetHref(appState, target, name), onclick: targetClick(nav, target, name) };
	}
</script>

<ul class="flex flex-col">
	{#each ordered as planet (planet.number)}
		{@const a = axis(planet)}
		{@const period = figure(planet, 'period')}
		{@const name = localName(planet)}
		<MemberRow
			{name}
			tile={planet.letter ?? String(planet.number)}
			{...link(planet, name)}
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
