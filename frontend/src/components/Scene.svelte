<script lang="ts">
	import { onMount, onDestroy, getContext, untrack } from 'svelte';
	import { SceneRenderer } from '$lib/scene/renderer';
	import { calibrationUi } from '$lib/scene/perf/calibration-state.svelte';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import type { SimClock } from '$lib/scene/state/clock.svelte';
	import {
		effectiveRadiusKm,
		isSurfaceFeature,
		type FeatureAnchor,
		type PositionedBody
	} from '$lib/types/objects';
	import { kmToScene } from '$lib/math/units';
	import type { LabelledPath, PathStep } from '$lib/travel/labelled-path';
	import type { OrbitPreview } from '$lib/scene/objects/travel/orbit-preview';
	import type { Hazard } from '$lib/travel/hazards';
	import { page } from '$app/state';
	import { sphericalToCartesian } from '$lib/math/spherical';
	import { navEndOf, parseUrl, urlTypeFromId } from '$lib/state/url';
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

	$effect(() => {
		// Read first: with `renderer?.` short-circuiting before onMount assigns the
		// renderer, an inline arg would never be read, so the signal goes untracked
		// and the effect never re-runs on toggle.
		const reduced = settings.resolvedReducedMotion;
		renderer?.setReducedMotion(reduced);
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

	/** Focus a surface feature as a real orbitable body seated on its host.
	 *  Standoff scales with feature size, floored and capped so it never
	 *  collapses or overshoots.
	 *
	 *  `mode`: `pan` re-aims in place (label click); `frame` flies to it
	 *  (search/sidebar); `snap` places it instantly for URL deep-links, where
	 *  `view` overrides the diameter-based framing. */
	export function focusOnFeature(
		bodyId: string,
		featureId: number,
		lat: number,
		lon: number,
		diameterM: number,
		name: string | null,
		mode: 'pan' | 'frame' | 'snap' = 'frame',
		view: { latitude: number; longitude: number; zoom: number } | null = null
	): number {
		const host = ctx.getBody(bodyId);
		if (!host) return 0;
		const idealScene = kmToScene((diameterM * 4) / 1000);
		const minScene = kmToScene(0.02);
		const maxScene = kmToScene(effectiveRadiusKm(host.data) * 5);
		const zoom = Math.min(Math.max(idealScene, minScene), maxScene);
		const anchor: FeatureAnchor = { hostId: bodyId, featureId, lat, lon, diameterM };
		return renderer?.focusOnFeature(anchor, name, zoom, mode, view) ?? 0;
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

	/** Draw the trip the planner is showing, and whatever it is being chosen from. */
	export function setTravelPath(
		plan: LabelledPath | null,
		options: readonly LabelledPath[] = [],
		hazards: readonly Hazard[] = [],
		steps: readonly PathStep[] = []
	): void {
		renderer?.setTravelPath(plan, options, hazards, steps);
	}

	/** Pick one of the offered trajectories out of the rest, or none. */
	/** Draw (or clear) the orbits the travel panel's ends are being picked in,
	 *  round their live bodies. `frame` names the ring being interacted with,
	 *  for the camera to put on screen. */
	export function setOrbitPreview(
		previews: readonly OrbitPreview[],
		frame: { bodyId: string; radiusKm: number } | null
	): void {
		renderer?.setOrbitPreview(previews, frame);
	}

	export function setTravelHover(id: string | null): void {
		renderer?.setTravelHover(id);
	}

	/** Look at a place on that trip, which is usually nowhere near a body. */
	export function focusOnPathPoint(centerId: string, rKm: readonly [number, number, number]): void {
		renderer?.focusOnPathPoint(centerId, rKm);
	}

	/** Follow a place along the trip without re-framing — for a dragged clock. */
	export function trackPathPoint(centerId: string, rKm: readonly [number, number, number]): void {
		renderer?.trackPathPoint(centerId, rKm);
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
	const RESTORE_PING_TIMEOUT_MS = 4000;
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
		// Generous timeout: the main thread is busy re-uploading every VBO and the
		// skybox here, so a live worker's pong can be slow to be read, and a false
		// negative costs a full repack of the main belt.
		void renderer?.recoverWorkersIfDead(RESTORE_PING_TIMEOUT_MS);
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
				// The camera orbits the synthetic feature body, but the app focuses its
				// host — the URL/drawer are set by the setFeature caller, so just report
				// the host upward and skip the generic body auto-setFocus below.
				if (body && isSurfaceFeature(body)) {
					onFocusChange?.(ctx.getBody(body.featureAnchor!.hostId));
					return;
				}
				onFocusChange?.(body);
				// Skip the auto-setFocus when the URL already names this body:
				// programmatic navigators (search, deep links) push their target
				// state first and would otherwise have featureId/groupSlug wiped
				// out by setFocus the moment the camera lands. Also skip when a
				// group is focused and the clicked body is a member — clicking
				// within a group should keep the group view, only the camera moves.
				if (!wasInitial && !isNavigatingBack && body && body.data.id !== appState.view.id) {
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

	// A deliberate jump (now button, date picker) shouldn't wait out the poll or
	// the throttle window — write it through the moment it happens.
	let seenJumps = 0;
	$effect(() => {
		const jumps = clock.jumps;
		if (jumps === seenJumps) return;
		seenJumps = jumps;
		untrack(() => {
			if (focusedBody) appState.setDate(jdToDate(clock.jd), isLive(), true);
		});
	});

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

	// User-triggered benchmark re-run: halt the map's render loop so the bench
	// measures an uncontended GPU. Resume must not race the context-lost pause.
	$effect(() => {
		const benchRunning = calibrationUi.progress !== null;
		if (!renderer) return;
		if (benchRunning) renderer.pause();
		else if (!renderer.isContextLost()) renderer.resume();
	});

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
	<div
		bind:this={labelContainer}
		class="scene-overlay absolute inset-0 pointer-events-none z-0"
	></div>
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
	{#if calibrationUi.progress !== null}
		<div
			class="absolute inset-0 z-20 flex flex-col items-center justify-center gap-4 bg-bg/60 backdrop-blur-sm pointer-events-auto"
		>
			<p class="text-sm text-text">{m.settings_recalibrate_running()}</p>
			<LoadingBar value={calibrationUi.progress} label={m.settings_recalibrate_running()} />
		</div>
	{/if}
	{#if settings.showDebugInfo && DebugMenu}
		<DebugMenu getRenderer={() => renderer} {ctx} {clock} />
	{/if}
	{#if settings.showSkyboxAlign && SkyboxDebugSliders}
		<SkyboxDebugSliders getRenderer={() => renderer} />
	{/if}
	{#if settings.showLightingTuner && LightingDebugSliders}
		<LightingDebugSliders getRenderer={() => renderer} />
	{/if}
</div>
