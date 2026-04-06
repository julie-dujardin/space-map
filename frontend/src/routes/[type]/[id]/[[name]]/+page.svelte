<script lang="ts">
	import { onMount, setContext } from 'svelte';
	import Scene from '../../../../components/Scene.svelte';
	import { ContextManager } from '$lib/scene/context-manager.svelte';
	import { type PositionedBody } from '$lib/types/objects';
	import { parseUrl, DEFAULT_VIEW } from '$lib/url-state';
	import ObjectDrawer from '../../../../components/detail/ObjectDrawer.svelte';
	import MyLocation from '../../../../components/MyLocation.svelte';
	import * as m from '$lib/paraglide/messages.js';

	const ctx = new ContextManager();
	setContext('ctx', ctx);

	const initialView = parseUrl() ?? DEFAULT_VIEW;
	let selectedBody = $state<PositionedBody | undefined>();
	let scene = $state<Scene>();

	onMount(() => ctx.load(initialView.date, initialView.id));
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
		<Scene bind:this={scene} {initialView} onFocusChange={(body) => (selectedBody = body)} />
		{#if selectedBody?.data.id}
			<ObjectDrawer body={selectedBody} onClose={() => (selectedBody = undefined)} />
		{/if}
		<div class="absolute bottom-4 right-4 z-10">
			<MyLocation onLocate={(zoom) => scene?.focusOnBody('naif-399', zoom)} />
		</div>
	</div>
{/if}
