<script lang="ts">
	import { onMount, getContext, untrack } from 'svelte';
	import type { SceneRenderer } from '$lib/scene/renderer';
	import type { MapController } from '$lib/scene/map-controller.svelte';
	import { calibrationUi } from '$lib/scene/perf/calibration-state.svelte';
	import type { PositionedBody } from '$lib/types/objects';
	import { page } from '$app/state';
	import { sphericalToCartesian } from '$lib/math/spherical';
	import { navEndOf, parseUrl, urlTypeFromId } from '$lib/state/url';
	import { UrlType } from '$lib/state/view';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { MapCover } from '$lib/state/map-cover.svelte';
	import { jdToDate } from '$lib/time/jd';
	import { getSettings } from '$lib/state/settings.svelte';
	import * as m from '$lib/paraglide/messages.js';
	import LoadingBar from './LoadingBar.svelte';
	import { startPageReload } from '$lib/reload';
	import { dismissNotice, showNotice } from '$lib/state/notices';

	const settings = getSettings();

	// Debug overlays are dev-only, gated behind settings toggles most users never
	// flip — lazy-load them so they stay out of the main map chunk.
	let DebugMenu = $state<typeof import('./DebugMenu.svelte').default | null>(null);
	let SkyboxDebugSliders = $state<typeof import('./SkyboxDebugSliders.svelte').default | null>(
		null
	);
	let LightingDebugSliders = $state<typeof import('./LightingDebugSliders.svelte').default | null>(
		null
	);
	$effect(() => {
		if (settings.showDebugInfo && !DebugMenu) {
			import('./DebugMenu.svelte').then((mod) => (DebugMenu = mod.default));
		}
		if (settings.showSkyboxAlign && !SkyboxDebugSliders) {
			import('./SkyboxDebugSliders.svelte').then((mod) => (SkyboxDebugSliders = mod.default));
		}
		if (settings.showLightingTuner && !LightingDebugSliders) {
			import('./LightingDebugSliders.svelte').then((mod) => (LightingDebugSliders = mod.default));
		}
	});

	/** The map itself lives in the controller; this component gives it a box,
	 *  keeps the URL in step with it, and draws the panels over it. */
	interface Props {
		map: MapController;
		northRefId?: string | null;
		onFocusChange?: (body: PositionedBody | undefined) => void;
		onUserPromotedChange?: (count: number) => void;
		onFeatureSelect?: (
			bodyId: string,
			featureId: number,
			lat: number,
			lon: number,
			diameterM: number
		) => void;
	}

	let {
		map,
		northRefId = null,
		onFocusChange,
		onUserPromotedChange,
		onFeatureSelect
	}: Props = $props();

	const appState = getContext<AppState>('appState');
	const mapCover = getContext<MapCover>('mapCover');
	// The map is fixed for the component's life; its parts are read once.
	// svelte-ignore state_referenced_locally
	const { ctx, clock } = map;

	let container: HTMLDivElement;
	let reloading = $state(false);
	const startReload = () => startPageReload(() => (reloading = true));
	const getRenderer = (): SceneRenderer | undefined => map.renderer ?? undefined;

	let isNavigatingBack = false;

	onMount(() => {
		// Listeners first: mounting builds the renderer, which settles the opening
		// focus synchronously — a deep link's only `focuschange` fires in there.
		const off = [
			map.on('focuschange', ({ body, initial, feature }) => {
				// The camera orbits the synthetic feature body, but the app focuses its
				// host — the URL/drawer are set by the setFeature caller, so just report
				// the host upward and skip the generic body auto-setFocus below.
				onFocusChange?.(body);
				if (feature || initial || isNavigatingBack || !body) return;
				// Skip the auto-setFocus when the URL already names this body:
				// programmatic navigators (search, deep links) push their target
				// state first and would otherwise have featureId/groupSlug wiped
				// out by setFocus the moment the camera lands. Also skip when a
				// group is focused and the clicked body is a member — clicking
				// within a group should keep the group view, only the camera moves.
				if (body.data.id === appState.view.id) return;
				// A trip stays a trip: settling on a body inside one moves where the
				// trip goes, since that is the question the page is asking.
				if (appState.view.type === UrlType.Nav) {
					// Where you set out from is not somewhere to go — that click just
					// moves the camera, as the endpoint search declines to offer it.
					if (body.data.id !== appState.view.navFrom) {
						appState.setNav(navEndOf(appState.view, 'from'), body.data.id);
					}
					return;
				}
				const inActiveGroup =
					appState.view.type === UrlType.Group &&
					appState.view.groupSlug !== null &&
					ctx.isMemberOfActiveGroup(body.data.id);
				if (!inActiveGroup) {
					appState.setFocus({
						type: urlTypeFromId(body.data.id),
						id: body.data.id,
						// Drawer fills the localized name via replaceFocusName once the detail bundle resolves.
						name: body.data.name ?? ''
					});
				}
			}),
			map.on('camera', (view) => {
				if (map.focusedBody) appState.setCamera(view);
			}),
			map.on('userpromoted', (count) => onUserPromotedChange?.(count)),
			map.on('featureselect', ({ bodyId, featureId, lat, lon, diameterM }) =>
				onFeatureSelect?.(bodyId, featureId, lat, lon, diameterM)
			),
			map.on('notice', showNotice),
			map.on('noticedismiss', dismissNotice)
		];
		map.mount(container);

		// Keep the URL's date on the sim clock so reload/share preserves the
		// moment; a clock still on wall-clock time keeps writing `now`.
		const clockSyncId = setInterval(() => {
			if (!map.focusedBody) return;
			appState.setDate(jdToDate(clock.jd), clock.live);
		}, 500);

		const onPopState = () => {
			const view = page.state.view ?? parseUrl();
			if (!view) return;
			const oldId = appState.view.id;
			appState.syncFromPopState(view);
			if (view.id === oldId) return;
			const body = ctx.getBody(view.id);
			const target = body?.position ?? map.focusedBody?.position ?? [0, 0, 0];
			const camPos = sphericalToCartesian(target, view.latitude, view.longitude, view.zoom);
			isNavigatingBack = true;
			if (body) map.setFocusTarget(body, camPos);
			isNavigatingBack = false;
		};
		window.addEventListener('popstate', onPopState);

		return () => {
			clearInterval(clockSyncId);
			window.removeEventListener('popstate', onPopState);
			for (const stop of off) stop();
			map.unmount();
		};
	});

	// A deliberate jump (now button, date picker) shouldn't wait out the poll or
	// the throttle window — write it through the moment it happens.
	let seenJumps = 0;
	$effect(() => {
		const jumps = clock.jumps;
		if (jumps === seenJumps) return;
		seenJumps = jumps;
		untrack(() => {
			if (map.focusedBody) appState.setDate(jdToDate(clock.jd), clock.live, true);
		});
	});

	$effect(() => {
		map.setNorthReference(northRefId);
	});

	// Read before the call, so the flag stays a dependency while the renderer is unset.
	$effect(() => {
		const hidden = mapCover.covered;
		map.setCovered(hidden);
	});
</script>

<div bind:this={container}>
	{#if map.webglError}
		<div
			role="alert"
			class="absolute inset-0 z-30 flex flex-col items-center justify-center gap-3 bg-bg px-6 text-center text-text"
		>
			<h2 class="text-lg font-semibold">{m.webgl_unavailable_title()}</h2>
			<p class="max-w-md text-sm text-muted-foreground">{m.webgl_unavailable_body()}</p>
		</div>
	{:else if map.contextLost}
		<div
			role="alert"
			class="absolute inset-0 z-30 flex flex-col items-center justify-center gap-4 bg-bg/90 px-6 text-center text-text backdrop-blur"
		>
			<h2 class="text-lg font-semibold">{m.webgl_context_lost_title()}</h2>
			<p class="max-w-md text-sm text-muted-foreground">{m.webgl_context_lost_body()}</p>
			<button
				class="rounded-md bg-text px-4 py-2 text-sm font-medium text-bg hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:opacity-50"
				disabled={reloading}
				onclick={startReload}
			>
				{m.reload()}
			</button>
			{#if reloading}
				<LoadingBar label={m.reload()} />
			{/if}
		</div>
	{/if}
	{#if calibrationUi.progress !== null}
		<div
			class="absolute inset-0 z-20 flex flex-col items-center justify-center gap-4 bg-bg/60 backdrop-blur-sm pointer-events-auto"
		>
			<p class="text-sm text-text">{m.settings_recalibrate_running()}</p>
			<LoadingBar value={calibrationUi.progress} label={m.settings_recalibrate_running()} />
		</div>
	{/if}
	{#if settings.showDebugInfo && DebugMenu}
		<DebugMenu {getRenderer} {ctx} {clock} />
	{/if}
	{#if settings.showSkyboxAlign && SkyboxDebugSliders}
		<SkyboxDebugSliders {getRenderer} />
	{/if}
	{#if settings.showLightingTuner && LightingDebugSliders}
		<LightingDebugSliders {getRenderer} />
	{/if}
</div>
