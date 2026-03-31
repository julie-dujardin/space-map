<script lang="ts">
	import { onMount } from 'svelte';
	import Scene from '../../../../components/Scene.svelte';
	import { loadChunk } from '$lib/fetch/elements/chunk';
	import { type PositionedBody } from '$lib/types';
	import { parseUrl, DEFAULT_VIEW, type MapViewState } from '$lib/url-state';
	import ObjectDrawer from '../../../../components/detail/ObjectDrawer.svelte';
	import * as m from '$lib/paraglide/messages.js';

	let majorBodies = $state<PositionedBody[]>([]);
	let minorBodies = $state<PositionedBody[]>([]);
	let selectedBody = $state<PositionedBody | undefined>();
	let loading = $state(true);
	let error = $state<string | null>(null);

	const initialView: MapViewState = parseUrl() ?? DEFAULT_VIEW;

	onMount(async () => {
		try {
			const major_chunks = await Promise.all([
				loadChunk('sun', 0, 0, initialView.date),
				loadChunk('sun', 1, 0, initialView.date)
			]);
			const minor_chunks = await Promise.all([
				loadChunk('sun', 2, 0, initialView.date),
				loadChunk('sun', 3, 0, initialView.date)
			]);

			majorBodies = major_chunks.reduce((accumulator, value) => accumulator.concat(value), []);
			minorBodies = minor_chunks.reduce((accumulator, value) => accumulator.concat(value), []);
			loading = false;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			loading = false;
		}
	});
</script>

<svelte:head>
	<title
		>{selectedBody?.data.name
			? `${selectedBody.data.name} - ${m.page_title()}`
			: m.page_title()}</title
	>
</svelte:head>

{#if loading}
	<div class="flex items-center justify-center h-screen bg-bg text-text">{m.loading_data()}</div>
{:else if error}
	<div class="flex items-center justify-center h-screen bg-bg text-text-error">
		{m.error_prefix({ error })}
	</div>
{:else}
	<div class="relative w-full h-screen">
		<Scene
			{majorBodies}
			{minorBodies}
			{initialView}
			onFocusChange={(body) => (selectedBody = body)}
		/>
		{#if selectedBody?.data.fileId}
			<ObjectDrawer body={selectedBody} onClose={() => (selectedBody = undefined)} />
		{/if}
	</div>
{/if}
