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
	import DebugMenu from './DebugMenu.svelte';
	import SkyboxDebugSliders from './SkyboxDebugSliders.svelte';
	import { getSettings } from '$lib/state/settings.svelte';

	const settings = getSettings();

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
		const zoom = Math.min(Math.max(idealScene, minDist * 2), maxScene);
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

	onMount(() => {
		renderer = new SceneRenderer(canvas, labelContainer, ctx, clock, initialView, {
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
						ctx.earthSatFilter?.has(body.data.id) === true;
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

	onDestroy(() => {
		renderer?.dispose();
	});
</script>

<div class="relative w-full h-full select-none" style="-webkit-user-select: none;">
	<canvas bind:this={canvas} class="w-full h-full block pointer-events-auto touch-none"></canvas>
	<div bind:this={labelContainer} class="absolute inset-0 pointer-events-none z-0"></div>
	{#if settings.showDebugInfo}
		<DebugMenu getRenderer={() => renderer} {ctx} {clock} />
	{/if}
	{#if settings.showSkyboxAlign}
		<SkyboxDebugSliders getRenderer={() => renderer} />
	{/if}
</div>
