<script lang="ts">
	import { onMount, setContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import Scene from '../../../../components/Scene.svelte';
	import { ContextManager } from '$lib/scene/context-manager.svelte';
	import { type PositionedBody } from '$lib/types/objects';
	import { parseUrl, DEFAULT_VIEW, serializeUrl } from '$lib/url-state';
	import ObjectDrawer from '../../../../components/detail/ObjectDrawer.svelte';
	import MyLocation from '../../../../components/MyLocation.svelte';
	import * as m from '$lib/paraglide/messages.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';

	const ctx = new ContextManager();
	setContext('ctx', ctx);

	const parsed = parseUrl();
	const initialView = parsed ?? DEFAULT_VIEW;
	let selectedBody = $state<PositionedBody | undefined>();
	let scene = $state<Scene>();
	let drawerHeightDvh = $state(0);

	onMount(async () => {
		await ctx.load(initialView.date, initialView.id);
		if (parsed && !ctx.getBody(parsed.id)) {
			toast.warning(m.object_not_found({ id: parsed.id }));
			const defaultUrl = serializeUrl(DEFAULT_VIEW);
			history.replaceState(history.state, '', defaultUrl);
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

{#if ctx.loading}
	<div class="flex items-center justify-center h-screen bg-bg text-text">{m.loading_data()}</div>
{:else if ctx.error}
	<div class="flex items-center justify-center h-screen bg-bg text-text-error">
		{m.error_prefix({ error: ctx.error })}
	</div>
{:else}
	<Tooltip.Provider delayDuration={300}>
		<div class="relative w-full h-screen">
			<Scene bind:this={scene} {initialView} onFocusChange={(body) => (selectedBody = body)} />
			{#if selectedBody?.data.id}
				<ObjectDrawer
					body={selectedBody}
					onClose={() => {
						selectedBody = undefined;
						drawerHeightDvh = 0;
					}}
					onSheetResize={(h) => (drawerHeightDvh = h)}
				/>
			{/if}
			<div
				class="fixed right-4 z-10 transition-opacity duration-300 ease-in-out
				{drawerHeightDvh > 12 ? 'opacity-0 pointer-events-none' : 'opacity-100'}"
				style="bottom: calc({Math.min(drawerHeightDvh, 12)}dvh + 1rem);"
			>
				<MyLocation onLocate={(zoom) => scene?.focusOnBody('naif-399', zoom) ?? 0} />
			</div>
		</div>
	</Tooltip.Provider>
{/if}
