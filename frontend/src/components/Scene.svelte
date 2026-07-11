<script lang="ts">
	import { onMount, onDestroy, getContext } from 'svelte';
	import { SceneRenderer } from '$lib/scene/renderer';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import type { SimClock } from '$lib/scene/state/clock.svelte';
	import { effectiveRadiusKm, type PositionedBody } from '$lib/types/objects';
	import { minCameraDistance } from '$lib/scene/visibility/camera-limits';
	import { kmToScene } from '$lib/math/units';
	import { page } from '$app/state';
	import { sphericalToCartesian } from '$lib/math/spherical';
	import { parseUrl, urlTypeFromId } from '$lib/state/url';
	import { UrlType } from '$lib/state/view';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { dateToJD, jdToDate } from '$lib/format/date';
	import { getSettings } from '$lib/state/settings.svelte';
	import * as m from '$lib/paraglide/messages.js';
	import LoadingBar from './LoadingBar.svelte';
	import { startPageReload } from '$lib/reload';

	const settings = getSettings();

	// Debug overlays are dev-only, gated behind settings toggles most users never
	// flip — lazy-load them so they stay out of the main map chunk.
	let DebugMenu = $state<typeof import('./DebugMenu.svelte').default | null>(null);
	let SkyboxDebugSliders = $state<typeof import('./SkyboxDebugSliders.svelte').default | null>(
		null
	);
	$effect(() => {
		if (settings.showDebugInfo && !DebugMenu) {
			import('./DebugMenu.svelte').then((mod) => (DebugMenu = mod.default));
		}
		if (settings.showSkyboxAlign && !SkyboxDebugSliders) {
			import('./SkyboxDebugSliders.svelte').then((mod) => (SkyboxDebugSliders = mod.default));
		}
	});

	interface Props {
		clock: SimClock;
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
		clock,
		northRefId = null,
		onFocusChange,
		onUserPromotedChange,
		onFeatureSelect
	}: Props = $props();

	const ctx = getContext<ContextManager>('ctx');
	const appState = getContext<AppState>('appState');
	const initialView = appState.view;

	let canvas: HTMLCanvasElement;
	let labelContainer: HTMLDivElement;
	let renderer: SceneRenderer | undefined;
	// WebGL couldn't start → panel instead of a black canvas. contextLost covers
	// a mid-session GPU context drop (common on mobile), unrecoverable in place.
	let webglError = $state(false);
	let contextLost = $state(false);
	let reloading = $state(false);
	const startReload = () => startPageReload(() => (reloading = true));
	// `.raw` to skip deep proxying — renderer mutates `position`/satrec internals every frame.
	let focusedBody = $state.raw<PositionedBody | undefined>();

	export function focusOnBody(
		id: string,
		zoom?: number,
		latitude?: number,
		longitude?: number
	): number {
		return renderer?.focusOnBody(id, zoom, latitude, longitude) ?? 0;
	}

	/** Instantly focus + frame a body (no fly) — for URL deep-links whose target
	 *  loaded after the initial render settled on the placeholder parent. */
	export function snapToBody(id: string, latitude: number, longitude: number, zoom: number): void {
		renderer?.snapToBody(id, latitude, longitude, zoom);
	}

	/** Snap focus onto a body, framed looking toward another body (e.g. the Sun) above the ecliptic. */
	export function snapToBodyFacing(
		id: string,
		towardId: string,
		elevationDeg: number,
		distance: number
	): void {
		renderer?.snapToBodyFacing(id, towardId, elevationDeg, distance);
	}

	/** Fly the camera onto a surface feature. Picks a zoom that frames the
	 *  feature: small craters get pulled in close, ocean-sized features stay
	 *  pulled back so they fit on screen. Clamped to the body's own min camera
	 *  distance below and a fraction of its radius above. All distances are
	 *  in scene units — `focusOnBody` writes camera positions in scene space,
	 *  so the km-side numbers go through `kmToScene` first.
	 *
	 *  `snap`: skip the fly animation and place the camera at the feature
	 *  framing immediately. Used on URL-load (`/<type>/<bodyId>/f/<featureId>/…`) so
	 *  the page opens already framed on the feature, not animating in from
	 *  the URL's `at=` framing. */
	export function focusOnFeature(
		bodyId: string,
		lat: number,
		lon: number,
		diameterM: number,
		snap = false
	): number {
		const body = ctx.getBody(bodyId);
		if (!body) return 0;
		const minDist = minCameraDistance(body);
		const idealScene = kmToScene((diameterM * 4) / 1000);
		const maxScene = kmToScene(effectiveRadiusKm(body.data) * 5);
		// Shape-model bodies: frame from the actual surface under the feature —
		// center-based distances make the approach altitude swing with the local
		// terrain radius (Eros spans 5–16 km lobe vs waist).
		const surface = renderer?.modelSurfaceRadiusScene(bodyId, lat, lon);
		const zoom =
			surface != null
				? Math.min(Math.max(surface + idealScene, minDist), maxScene)
				: Math.min(Math.max(idealScene, minDist * 2), maxScene);
		if (snap) {
			renderer?.snapToBodyFrame(lat, lon, zoom);
			return 0;
		}
		return renderer?.focusOnBody(bodyId, zoom, lat, lon) ?? 0;
	}

	export function setUserLocation(latitude: number, longitude: number): void {
		renderer?.setUserLocation(latitude, longitude);
	}

	export function clearUserPromoted(): void {
		renderer?.clearUserPromoted();
	}

	export function setSelectedFeature(featureId: number | null): void {
		renderer?.setSelectedFeature(featureId);
	}

	function isLive(): boolean {
		// Within ~1 day of wall clock and playing at 1× → URL omits the time.
		return clock.timeScale === 1 && Math.abs(clock.jd - dateToJD(new Date())) < 1;
	}

	function syncCameraToUrl(latitude: number, longitude: number, zoom: number) {
		if (!focusedBody) return;
		appState.setCamera({ latitude, longitude, zoom });
	}

	let isInitialFocus = true;
	let isNavigatingBack = false;

	// Reclaiming a backgrounded mobile tab drops the GL context (and can kill
	// workers). preventDefault opts into the browser's own restore on tab return.
	let lostOverlayTimer: ReturnType<typeof setTimeout> | undefined;
	function onContextLost(e: Event) {
		e.preventDefault();
		console.warn('[scene] WebGL context lost');
		renderer?.pause();
		// Defer the "stopped" panel — restore usually lands within a frame or two,
		// so showing it immediately would just flash.
		clearTimeout(lostOverlayTimer);
		lostOverlayTimer = setTimeout(() => (contextLost = true), 2000);
	}

	function onContextRestored() {
		console.warn('[scene] WebGL context restored');
		clearTimeout(lostOverlayTimer);
		contextLost = false;
		renderer?.handleContextRestored();
		// Context loss often coincides with dead workers, which onVisibility skips
		// while the context is lost — so probe here too (no-op if they survived).
		void renderer?.recoverWorkersIfDead();
	}

	// OS-killed workers fire no event; probe on tab-return to recover frozen clouds.
	function onVisibility() {
		if (document.visibilityState !== 'visible') return;
		if (renderer?.isContextLost()) return; // handled by the restore event
		void renderer?.recoverWorkersIfDead();
	}

	onMount(() => {
		canvas.addEventListener('webglcontextlost', onContextLost, false);
		canvas.addEventListener('webglcontextrestored', onContextRestored, false);
		document.addEventListener('visibilitychange', onVisibility);

		let cleanupInner = () => {};
		try {
			renderer = buildRenderer();
			cleanupInner = wireRenderer();
		} catch (e) {
			console.error('[scene] renderer init failed:', e);
			webglError = true;
		}

		return () => {
			clearTimeout(lostOverlayTimer);
			canvas.removeEventListener('webglcontextlost', onContextLost);
			canvas.removeEventListener('webglcontextrestored', onContextRestored);
			document.removeEventListener('visibilitychange', onVisibility);
			cleanupInner();
		};
	});

	function buildRenderer(): SceneRenderer {
		return new SceneRenderer(canvas, labelContainer, ctx, clock, initialView, {
			onFocusChange(body) {
				const wasInitial = isInitialFocus;
				isInitialFocus = false;
				focusedBody = body;
				onFocusChange?.(body);
				// Skip the auto-setFocus when the URL already names this body:
				// programmatic navigators (search, deep links) push their target
				// state first and would otherwise have featureId/groupSlug wiped
				// out by setFocus the moment the camera lands. Also skip when a
				// group is focused and the clicked body is a member — clicking
				// within a group should keep the group view, only the camera moves.
				if (!wasInitial && !isNavigatingBack && body && body.data.id !== appState.view.id) {
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
				}
			},
			onCameraPosition: syncCameraToUrl,
			onUserPromotedChange(count) {
				onUserPromotedChange?.(count);
			},
			onFeatureSelect(bodyId, featureId, lat, lon, diameterM) {
				onFeatureSelect?.(bodyId, featureId, lat, lon, diameterM);
			}
		});
	}

	/** Wire the resize observer, clock→URL sync, and popstate handler. Returns
	 *  their teardown. Only called once the renderer built successfully. */
	function wireRenderer(): () => void {
		const ro = new ResizeObserver(() => {
			renderer?.resize(canvas.clientWidth, canvas.clientHeight);
		});
		ro.observe(canvas);

		// Keep the URL's time stamp in sync with the sim clock so reload/share preserves the moment.
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
	}

	$effect(() => {
		void ctx.bodies.minorBodyVersion; // reactive dependency — re-runs on each flush
		renderer?.rebuildMinorPointClouds();
	});

	$effect(() => {
		renderer?.setNorthReference(northRefId);
	});

	$effect(() => {
		renderer?.setImmersive(settings.viewMode === 'immersive');
	});

	$effect(() => {
		renderer?.setHaloDebugVisible(settings.showHaloDebug);
	});

	// Keyboard camera controls: arrows orbit the focused body, +/- zoom, Shift
	// speeds up. Mirrors OrbitControls' pointer gestures for keyboard-only users.
	const KEY_ROTATE_RAD = 0.05;
	const KEY_ZOOM_FACTOR = 1.15;
	function onCanvasKeyDown(e: KeyboardEvent) {
		if (e.ctrlKey || e.metaKey || e.altKey) return;
		const step = (e.shiftKey ? 4 : 1) * KEY_ROTATE_RAD;
		let azimuth = 0;
		let polar = 0;
		let dolly = 1;
		switch (e.key) {
			case 'ArrowLeft':
				azimuth = step;
				break;
			case 'ArrowRight':
				azimuth = -step;
				break;
			case 'ArrowUp':
				polar = step;
				break;
			case 'ArrowDown':
				polar = -step;
				break;
			case '+':
			case '=':
				dolly = KEY_ZOOM_FACTOR;
				break;
			case '-':
			case '_':
				dolly = 1 / KEY_ZOOM_FACTOR;
				break;
			default:
				return;
		}
		e.preventDefault();
		renderer?.nudgeCamera(azimuth, polar, dolly);
	}

	onDestroy(() => {
		renderer?.dispose();
	});
</script>

<div class="relative w-full h-full select-none" style="-webkit-user-select: none;">
	<!-- role="application" hands arrow keys through screen readers to the map;
	     Svelte's lint table misclassifies it as noninteractive on canvas. -->
	<!-- svelte-ignore a11y_no_interactive_element_to_noninteractive_role -->
	<canvas
		bind:this={canvas}
		tabindex="0"
		role="application"
		aria-label={m.scene_canvas_label()}
		onkeydown={onCanvasKeyDown}
		class="w-full h-full block pointer-events-auto touch-none focus-visible:outline-2 focus-visible:outline-ring"
	></canvas>
	<div bind:this={labelContainer} class="absolute inset-0 pointer-events-none z-0"></div>
	{#if webglError}
		<div
			role="alert"
			class="absolute inset-0 z-30 flex flex-col items-center justify-center gap-3 bg-bg px-6 text-center text-text"
		>
			<h2 class="text-lg font-semibold">{m.webgl_unavailable_title()}</h2>
			<p class="max-w-md text-sm text-muted-foreground">{m.webgl_unavailable_body()}</p>
		</div>
	{:else if contextLost}
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
	{#if settings.showDebugInfo && DebugMenu}
		<DebugMenu getRenderer={() => renderer} {ctx} {clock} />
	{/if}
	{#if settings.showSkyboxAlign && SkyboxDebugSliders}
		<SkyboxDebugSliders getRenderer={() => renderer} />
	{/if}
</div>
