<script lang="ts">
	import { onMount, setContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import Scene from '../../../../components/Scene.svelte';
	import { ContextManager } from '$lib/scene/context-manager.svelte';
	import { SimClock } from '$lib/scene/clock.svelte';
	import { dateToJD } from '$lib/format/date';
	import { ObjectType, type PositionedBody } from '$lib/types/objects';
	import { minCameraDistance } from '$lib/scene/visibility/camera-limits';
	import { DEFAULT_VIEW } from '$lib/state/view';
	import { createAppState } from '$lib/state/app-state.svelte';
	import ObjectDrawer from '../../../../components/detail/ObjectDrawer.svelte';
	import MyLocation from '../../../../components/MyLocation.svelte';
	import AttributionBar from '../../../../components/AttributionBar.svelte';
	import TimeControls from '../../../../components/TimeControls.svelte';
	import MobileTimeControls from '../../../../components/MobileTimeControls.svelte';
	import * as m from '$lib/paraglide/messages.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';

	const ctx = new ContextManager();
	setContext('ctx', ctx);

	const appState = createAppState();
	setContext('appState', appState);

	const clock = new SimClock(dateToJD(appState.view.date));
	// `.raw` — see Scene.svelte's `focusedBody` for the rationale (avoids deep
	// proxying of position/satrec, which the renderer and SGP4 mutate).
	let selectedBody = $state.raw<PositionedBody | undefined>();
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
		>{selectedBody && appState.view.name
			? `${appState.view.name} - ${m.page_title()}`
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
					onMaximize={() => {
						if (!selectedBody) return;
						scene?.focusOnBody(selectedBody.data.id, minCameraDistance(selectedBody) * 5);
					}}
					onMinimize={() => {
						if (!selectedBody) return;
						// Pulls the camera back without changing focus — focusOnBody on the
						// already-focused id just runs the fly-to-camera path. Planets and
						// dwarf planets nominally orbit their planetary barycenter, but
						// treat them as sun-orbiters here so the minimize framing is the
						// whole solar system instead of just the planet's own subsystem.
						const { parentId, objectType } = selectedBody.data;
						const isSunOrbiter =
							parentId === 'naif-0' ||
							parentId === 'naif-10' ||
							objectType === ObjectType.PLANET ||
							objectType === ObjectType.DWARF_PLANET;
						const distance = isSunOrbiter ? DEFAULT_VIEW.zoom : 0.005;
						scene?.focusOnBody(selectedBody.data.id, distance);
					}}
					onSheetResize={(h) => (drawerHeightDvh = h)}
				/>
			{/if}
			<div
				class="fixed end-4 z-10 flex flex-col-reverse items-end gap-3 transition-[opacity,bottom] duration-300 ease-in-out
				{drawerHeightDvh > 12 ? 'opacity-0 pointer-events-none' : 'opacity-100'}"
				style="bottom: calc({Math.min(drawerHeightDvh, 12)}dvh + 1.5rem);"
			>
				<MyLocation
					onLocate={(zoom: number, lat?: number, lng?: number) =>
						scene?.focusOnBody('naif-399', zoom, lat, lng) ?? 0}
				/>
				<div class="md:hidden pointer-events-auto">
					<MobileTimeControls {clock} />
				</div>
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
