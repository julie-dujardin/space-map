<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalGroupData } from '$lib/fetch/groups/details';
	import { fetchGroupIndex, type GroupIndex } from '$lib/fetch/groups/registry';
	import { fetchOrbitSamples } from '$lib/fetch/groups/orbit-samples';
	import { fetchSatOrbitSamples } from '$lib/fetch/groups/sat-orbit-samples';
	import {
		plotTypeForSlug,
		type OrbitSample,
		type EarthOrbitSample,
		type PlotType
	} from '$lib/charts/orbit-zones';
	import { getContext } from 'svelte';
	import LoaderCircleIcon from '@lucide/svelte/icons/loader-circle';
	import type { AppState } from '$lib/state/app-state.svelte';
	import OrbitClassScatter from './OrbitClassScatter.svelte';
	import EarthOrbitScatter from './EarthOrbitScatter.svelte';

	interface Props {
		global: GlobalGroupData | null;
		/** Category pages force the plot (their slug isn't an orbit class). */
		plotOverride?: PlotType;
	}
	let { global, plotOverride }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');

	let plotType = $derived(plotOverride ?? (global ? plotTypeForSlug(global.slug) : null));
	let samples = $state<OrbitSample[] | null>(null);
	let satSamples = $state<EarthOrbitSample[] | null>(null);
	let groupIndex = $state<GroupIndex | null>(null);
	let populationBySlug = $derived.by(() => {
		const out: Record<string, number> = {};
		if (!groupIndex) return out;
		for (const [slug, entry] of Object.entries(groupIndex)) {
			out[slug] = entry.n;
		}
		return out;
	});

	$effect(() => {
		if (plotType == null) return;
		if (plotType === 'peri-apo') {
			if (satSamples == null) fetchSatOrbitSamples().then((s) => (satSamples = s));
		} else if (samples == null) {
			fetchOrbitSamples().then((s) => (samples = s));
		}
		if (groupIndex == null) fetchGroupIndex().then((g) => (groupIndex = g));
	});

	function handleZoneClick(slug: string) {
		if (!appState) return;
		appState.setGroup(slug, slug);
	}
</script>

{#if global && plotType}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{m.scatter_membership_title()}</h3>
		<div class="border-border/60 border-t"></div>
		<div class="pt-1">
			{#if plotType === 'peri-apo' && satSamples}
				<EarthOrbitScatter
					samples={satSamples}
					focusedSlug={global.slug}
					{populationBySlug}
					onZoneClick={handleZoneClick}
				/>
			{:else if plotType !== 'peri-apo' && samples}
				<OrbitClassScatter
					{samples}
					focusedSlug={global.slug}
					{plotType}
					{populationBySlug}
					onZoneClick={handleZoneClick}
				/>
			{:else}
				<div
					class="text-muted-foreground flex items-center justify-center"
					style:height="{plotType === 'peri-apo' ? 280 : 240}px"
				>
					<LoaderCircleIcon class="size-6 animate-spin" />
				</div>
			{/if}
		</div>
	</div>
{/if}
