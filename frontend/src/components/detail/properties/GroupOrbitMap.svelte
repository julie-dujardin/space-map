<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalGroupData } from '$lib/fetch/groups/details';
	import { fetchGroupIndex, type GroupIndex } from '$lib/fetch/groups/registry';
	import { fetchOrbitSamples } from '$lib/fetch/groups/orbit-samples';
	import { plotTypeForSlug, type OrbitSample } from '$lib/charts/orbit-zones';
	import { getContext } from 'svelte';
	import type { AppState } from '$lib/state/app-state.svelte';
	import OrbitClassScatter from './OrbitClassScatter.svelte';

	interface Props {
		global: GlobalGroupData | null;
	}
	let { global }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');

	let plotType = $derived(global ? plotTypeForSlug(global.slug) : null);
	let samples = $state<OrbitSample[] | null>(null);
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
		if (samples == null) fetchOrbitSamples().then((s) => (samples = s));
		if (groupIndex == null) fetchGroupIndex().then((g) => (groupIndex = g));
	});

	function handleZoneClick(slug: string) {
		if (!appState) return;
		appState.setGroup(slug, slug);
	}
</script>

{#if global && plotType && samples}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{m.scatter_membership_title()}</h3>
		<div class="border-border/60 border-t"></div>
		<div class="pt-1">
			<OrbitClassScatter
				{samples}
				focusedSlug={global.slug}
				{plotType}
				{populationBySlug}
				onZoneClick={handleZoneClick}
			/>
		</div>
	</div>
{/if}
