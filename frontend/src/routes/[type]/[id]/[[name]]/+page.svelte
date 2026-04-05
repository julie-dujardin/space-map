<script lang="ts">
	import { onMount, setContext } from 'svelte';
	import Scene from '../../../../components/Scene.svelte';
	import { ContextManager } from '$lib/scene/context-manager.svelte';
	import { type PositionedBody } from '$lib/types/objects';
	import { parseUrl, DEFAULT_VIEW } from '$lib/url-state';
	import ObjectDrawer from '../../../../components/detail/ObjectDrawer.svelte';
	import * as m from '$lib/paraglide/messages.js';

	const ctx = new ContextManager();
	setContext('ctx', ctx);

	const initialView = parseUrl() ?? DEFAULT_VIEW;
	let selectedBody = $state<PositionedBody | undefined>();

	onMount(() => ctx.load(initialView.date));
</script>

<svelte:head>
	<title
		>{selectedBody?.data.name
			? `${selectedBody.data.name} - ${m.page_title()}`
			: m.page_title()}</title
	>
</svelte:head>

{#if ctx.loading}
	<div class="flex items-center justify-center h-screen bg-bg text-text">{m.loading_data()}</div>
{:else if ctx.error}
	<div class="flex items-center justify-center h-screen bg-bg text-text-error">
		{m.error_prefix({ error: ctx.error })}
	</div>
{:else}
	<div class="relative w-full h-screen">
		<Scene {initialView} onFocusChange={(body) => (selectedBody = body)} />
		{#if selectedBody?.data.id}
			<ObjectDrawer body={selectedBody} onClose={() => (selectedBody = undefined)} />
		{/if}
	</div>
{/if}
