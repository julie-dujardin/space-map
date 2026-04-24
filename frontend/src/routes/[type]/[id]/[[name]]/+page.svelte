<script lang="ts">
	import { onMount, setContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import Scene from '../../../../components/Scene.svelte';
	import { ContextManager } from '$lib/scene/context-manager.svelte';
	import { SimClock } from '$lib/scene/clock.svelte';
	import { dateToJD } from '$lib/format/date';
	import { type PositionedBody } from '$lib/types/objects';
	import { minCameraDistance } from '$lib/scene/visibility/camera-limits';
	import { DEFAULT_VIEW } from '$lib/state/view';
	import { createAppState } from '$lib/state/app-state.svelte';
	import ObjectDrawer from '../../../../components/detail/ObjectDrawer.svelte';
	import MyLocation from '../../../../components/MyLocation.svelte';
	import AttributionBar from '../../../../components/AttributionBar.svelte';
	import TimeControls from '../../../../components/TimeControls.svelte';
	import * as m from '$lib/paraglide/messages.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';

	const ctx = new ContextManager();
	setContext('ctx', ctx);

	const appState = createAppState();
	setContext('appState', appState);

	const clock = new SimClock(dateToJD(appState.view.date));
	let selectedBody = $state<PositionedBody | undefined>();
	let scene = $state<Scene>();
	let drawerHeightDvh = $state(0);

	onMount(async () => {
		const initialId = appState.view.id;
		await ctx.load(appState.view.date, initialId);
		if (!ctx.getBody(initialId)) {
			toast.warning(m.object_not_found({ id: initialId }));
			appState.setFocus({ type: DEFAULT_VIEW.type, id: DEFAULT_VIEW.id, name: DEFAULT_VIEW.name });
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
			<Scene bind:this={scene} {clock} onFocusChange={(body) => (selectedBody = body)} />
			<TimeControls {clock} />
			{#if selectedBody?.data.id}
				<ObjectDrawer
					body={selectedBody}
					{clock}
					onClose={() => {
						selectedBody = undefined;
						drawerHeightDvh = 0;
					}}
					onGoTo={() => {
						if (!selectedBody) return;
						scene?.focusOnBody(selectedBody.data.id, minCameraDistance(selectedBody) * 5);
					}}
					onSheetResize={(h) => (drawerHeightDvh = h)}
				/>
			{/if}
			<div
				class="fixed end-4 z-10 transition-[opacity,bottom] duration-300 ease-in-out
				{drawerHeightDvh > 12 ? 'opacity-0 pointer-events-none' : 'opacity-100'}"
				style="bottom: calc({Math.min(drawerHeightDvh, 12)}dvh + 1.5rem);"
			>
				<MyLocation
					onLocate={(zoom: number, lat?: number, lng?: number) =>
						scene?.focusOnBody('naif-399', zoom, lat, lng) ?? 0}
				/>
			</div>
			<div
				class="fixed end-0 z-10 transition-opacity duration-300 ease-in-out
				{drawerHeightDvh > 12 ? 'opacity-0 pointer-events-none' : 'opacity-100'}"
				style="bottom: {Math.min(drawerHeightDvh, 12)}dvh;"
			>
				<AttributionBar />
			</div>
		</div>
	</Tooltip.Provider>
{/if}
