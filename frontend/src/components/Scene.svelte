<script lang="ts">
	import { onMount, onDestroy, getContext } from 'svelte';
	import { SceneRenderer } from '$lib/scene/renderer';
	import type { ContextManager } from '$lib/scene/context-manager.svelte';
	import type { SimClock } from '$lib/scene/clock.svelte';
	import type { PositionedBody } from '$lib/types/objects';
	import { page } from '$app/state';
	import { sphericalToCartesian } from '$lib/math/spherical';
	import { parseUrl, urlTypeFromId } from '$lib/state/url';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { dateToJD, jdToDate } from '$lib/format/date';
	import DebugOverlay from './DebugOverlay.svelte';
	import { getSettings } from '$lib/state/settings.svelte';

	const settings = getSettings();

	interface Props {
		clock: SimClock;
		northRefId?: string | null;
		onFocusChange?: (body: PositionedBody | undefined) => void;
		onUserPromotedChange?: (count: number) => void;
	}

	let { clock, northRefId = null, onFocusChange, onUserPromotedChange }: Props = $props();

	const ctx = getContext<ContextManager>('ctx');
	const appState = getContext<AppState>('appState');
	const initialView = appState.view;

	let canvas: HTMLCanvasElement;
	let labelContainer: HTMLDivElement;
	let renderer: SceneRenderer | undefined;
	// `.raw` so the body's inner fields (position arrays, satrec internals)
	// aren't deep-proxied — the renderer mutates `position` every frame and
	// SGP4 mutates `satrec` internals, neither of which should trigger Svelte
	// reactivity (and the proxy would also trip state_unsafe_mutation when
	// SGP4 is invoked from a `$derived`, e.g. the sub-point lat/lon).
	let focusedBody = $state.raw<PositionedBody | undefined>();

	export function focusOnBody(
		id: string,
		zoom?: number,
		latitude?: number,
		longitude?: number
	): number {
		return renderer?.focusOnBody(id, zoom, latitude, longitude) ?? 0;
	}

	export function setUserLocation(latitude: number, longitude: number): void {
		renderer?.setUserLocation(latitude, longitude);
	}

	export function clearUserPromoted(): void {
		renderer?.clearUserPromoted();
	}

	function isLive(): boolean {
		const jd = clock.jd;
		const wallJd = dateToJD(new Date());
		// Within ~1 day of wall clock and playing at 1× → treat as "live".
		// Keeps the URL showing "now" for a normally-running session and
		// preserves shareable snapshots when the user has scrubbed or paused.
		return clock.timeScale === 1 && Math.abs(jd - wallJd) < 1;
	}

	function syncCameraToUrl(latitude: number, longitude: number, zoom: number) {
		if (!focusedBody) return;
		appState.setCamera({ latitude, longitude, zoom });
	}

	let isInitialFocus = true;
	let isNavigatingBack = false;

	onMount(() => {
		renderer = new SceneRenderer(canvas, labelContainer, ctx, clock, initialView, {
			onFocusChange(body) {
				const wasInitial = isInitialFocus;
				isInitialFocus = false;
				focusedBody = body;
				onFocusChange?.(body);
				if (!wasInitial && !isNavigatingBack && body) {
					appState.setFocus({
						type: urlTypeFromId(body.data.id),
						id: body.data.id,
						// Empty while the localized name is still loading; the drawer
						// fills it in via replaceFocusName once the detail bundle resolves.
						name: body.data.name ?? ''
					});
				}
			},
			onCameraPosition: syncCameraToUrl,
			onUserPromotedChange(count) {
				onUserPromotedChange?.(count);
			}
		});

		const ro = new ResizeObserver(() => {
			renderer?.resize(canvas.clientWidth, canvas.clientHeight);
		});
		ro.observe(canvas);

		// Keep the URL's time stamp in sync with the sim clock so reload/share
		// preserves the current moment. Same 250ms debounce as camera sync.
		const clockSyncId = setInterval(() => {
			if (!focusedBody) return;
			appState.setDate(jdToDate(clock.jd), isLive());
		}, 500);

		const onPopState = () => {
			const view = page.state.view ?? parseUrl();
			if (!view) return;
			const oldId = appState.view.id;
			appState.syncFromPopState(view);
			if (view.id === oldId) return;
			const body = ctx.getBody(view.id);
			const target = body?.position ?? renderer?.getFocusedBody()?.position ?? [0, 0, 0];
			const camPos = sphericalToCartesian(target, view.latitude, view.longitude, view.zoom);
			isNavigatingBack = true;
			if (body) renderer?.setFocusTarget(body, camPos);
			isNavigatingBack = false;
		};
		window.addEventListener('popstate', onPopState);

		return () => {
			clearInterval(clockSyncId);
			ro.disconnect();
			window.removeEventListener('popstate', onPopState);
		};
	});

	$effect(() => {
		void ctx.minorBodyVersion; // reactive dependency — re-runs on each flush
		renderer?.rebuildMinorPointClouds();
	});

	$effect(() => {
		renderer?.setNorthReference(northRefId);
	});

	onDestroy(() => {
		renderer?.dispose();
	});
</script>

<div class="relative w-full h-full select-none" style="-webkit-user-select: none;">
	<canvas bind:this={canvas} class="w-full h-full block pointer-events-auto touch-none"></canvas>
	<div bind:this={labelContainer} class="absolute inset-0 pointer-events-none z-0"></div>
	{#if settings.showDebugInfo}
		<DebugOverlay getRenderer={() => renderer} {ctx} {clock} />
	{/if}
</div>
