<!-- An extrasolar object's values, grouped by meaning. -->
<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { tabHref } from '$lib/state/focus-link';
	import { isModifiedClick } from '$lib/modified-click';
	import Section from '../kit/Section.svelte';
	import TemperatureScale from '../kit/TemperatureScale.svelte';
	import StarRowList from './StarRowList.svelte';
	import type { StarSection } from './star-rows';

	interface Props {
		sections: StarSection[];
	}

	let { sections }: Props = $props();

	const appState = getContext<AppState>('appState');
	let structureHref = $derived(tabHref(appState, 'structure'));

	function openStructure(e: MouseEvent) {
		if (isModifiedClick(e)) return;
		e.preventDefault();
		appState.setTab('structure');
	}
</script>

{#each sections as section (section.key)}
	{#snippet rowList()}
		<StarRowList rows={section.rows} />
	{/snippet}
	{#snippet scale()}
		{#if section.temperature}
			<TemperatureScale
				temperatures={section.temperature.temperatures}
				valueTooltip={section.temperature.valueTooltip}
				estimatedNote={section.temperature.estimatedNote}
			/>
		{/if}
	{/snippet}
	<!-- Section leaves space for each snippet it gets, so it gets only the ones with content. -->
	<Section
		title={section.title}
		activateHref={section.structure ? structureHref : undefined}
		onActivate={section.structure ? openStructure : undefined}
		activateLabel={section.structure ? m.structure_see_layers() : undefined}
		children={section.rows.length ? rowList : undefined}
		footer={section.temperature ? scale : undefined}
	/>
{/each}
