<!--
  The record of a planet in its system file, one section per group of values.
  A row that names a page of the map links to it; a catalogue row leads off
  the site.
-->
<script lang="ts">
	import { getContext } from 'svelte';
	import Section from '../kit/Section.svelte';
	import Row from '../kit/Row.svelte';
	import Link from '../kit/Link.svelte';
	import { targetClick, targetHref } from '$lib/state/focus-link';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusFeature, FocusObject } from '$lib/state/focusable';
	import type { PlanetSection } from './planet-rows';

	interface Props {
		sections: PlanetSection[];
	}

	let { sections }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');
	const focusFeature = getContext<FocusFeature | undefined>('focusFeature');
	let nav = $derived({ appState, focusObject, focusFeature });
</script>

{#each sections as section (section.key)}
	<Section title={section.title}>
		{#each section.rows as entry, i (`${entry.label}-${i}`)}
			{#if entry.target}
				<Row label={entry.label} note={entry.note} labelIsName={entry.labelIsName}>
					<Link
						href={targetHref(appState, entry.target, entry.value)}
						onclick={targetClick(nav, entry.target, entry.value)}>{entry.value}</Link
					>
				</Row>
			{:else if entry.href}
				<Row label={entry.label} note={entry.note} labelIsName={entry.labelIsName}>
					<Link href={entry.href} external>{entry.value}</Link>
				</Row>
			{:else}
				<Row
					label={entry.label}
					value={entry.value}
					valueTooltip={entry.tooltip}
					note={entry.note}
					labelIsName={entry.labelIsName}
				/>
			{/if}
		{/each}
	</Section>
{/each}
