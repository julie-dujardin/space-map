<script lang="ts">
	import { onMount } from 'svelte';
	import Scene from '../../../../components/Scene.svelte';
	import { ChunkLoader } from '$lib/fetch/elements/chunk';
	import { type PositionedBody } from '$lib/types/objects';
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
			const loader = new ChunkLoader();
			majorBodies = majorBodies.concat(await loader.process('sun', 0, 0, initialView.date));

			majorBodies = majorBodies.concat(await loader.process('sun', 1, 0, initialView.date));

			const metaRes = await fetch('/data/v1/metadata.json');
			if (!metaRes.ok) throw new Error(`Failed to fetch metadata: ${metaRes.status}`);
			const metadata = await metaRes.json();

			const minorChunkArgs: { context: string; zoom: number; part: number }[] = [];
			for (const [context, ctxData] of Object.entries(metadata.contexts) as [
				string,
				{ zooms: Record<string, { parts: number }> }
			][]) {
				for (const [zoomStr, zoomData] of Object.entries(ctxData.zooms)) {
					if (context != 'sun' || Number(zoomStr) >= 2)
						for (let part = 0; part < Math.min(zoomData.parts, 20); part++) {
							minorChunkArgs.push({ context, zoom: Number(zoomStr), part });
						}
				}
			}

			const minor_chunks = await Promise.all(
				minorChunkArgs.map(({ context, zoom, part }) =>
					loader.process(context, zoom, part, initialView.date)
				)
			);

			minorBodies = minor_chunks.flat();

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
