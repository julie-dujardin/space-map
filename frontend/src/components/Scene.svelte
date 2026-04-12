<script lang="ts">
	import { onMount, onDestroy, getContext } from 'svelte';
	import { SceneRenderer } from '$lib/scene/renderer';
	import type { ContextManager } from '$lib/scene/context-manager.svelte';
	import type { SimClock } from '$lib/scene/clock.svelte';
	import type { PositionedBody } from '$lib/types/objects';
	import { page } from '$app/state';
	import {
		type MapViewState,
		sphericalToCartesian,
		writeUrlState,
		pushUrlState,
		parseUrl,
		urlTypeFromId
	} from '$lib/url-state';
	import { dateToJD, jdToDate } from '$lib/format/date';

	interface Props {
		initialView: MapViewState;
		clock: SimClock;
		onFocusChange?: (body: PositionedBody | undefined) => void;
	}

	let { initialView, clock, onFocusChange }: Props = $props();

	const ctx = getContext<ContextManager>('ctx');

	let canvas: HTMLCanvasElement;
	let labelContainer: HTMLDivElement;
	let renderer: SceneRenderer | undefined;
	let focusedBody = $state<PositionedBody | undefined>();

	export function focusOnBody(
		id: string,
		zoom?: number,
		latitude?: number,
		longitude?: number
	): number {
		return renderer?.focusOnBody(id, zoom, latitude, longitude) ?? 0;
	}

	let lastCameraPos = {
		latitude: initialView.latitude,
		longitude: initialView.longitude,
		zoom: initialView.zoom
	};

	function currentViewState(
		body: PositionedBody,
		cam: { latitude: number; longitude: number; zoom: number }
	): MapViewState {
		const jd = clock.jd;
		const wallJd = dateToJD(new Date());
		// Within ~1 day of wall clock and playing at 1× → treat as "live".
		// This keeps the URL showing "now" for a normally-running session and
		// preserves shareable snapshots when the user has scrubbed or paused.
		const isNow = clock.timeScale === 1 && Math.abs(jd - wallJd) < 1;
		return {
			type: urlTypeFromId(body.data.id),
			id: body.data.id,
			name: body.data.name ?? '',
			date: jdToDate(jd),
			isNow,
			latitude: cam.latitude,
			longitude: cam.longitude,
			zoom: cam.zoom
		};
	}

	function syncUrl(latitude: number, longitude: number, zoom: number) {
		lastCameraPos = { latitude, longitude, zoom };
		if (!focusedBody) return;
		writeUrlState(currentViewState(focusedBody, lastCameraPos));
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
					pushUrlState(currentViewState(body, lastCameraPos));
				}
			},
			onCameraPosition: syncUrl
		});

		const ro = new ResizeObserver(() => {
			renderer?.resize(canvas.clientWidth, canvas.clientHeight);
		});
		ro.observe(canvas);

		// Keep the URL's time stamp in sync with the sim clock so reload/share
		// preserves the current moment. Goes through the same 250ms debounce
		// as camera sync — nothing writes more than once per debounce window.
		const clockSyncId = setInterval(() => {
			if (!focusedBody) return;
			writeUrlState(currentViewState(focusedBody, lastCameraPos));
		}, 500);

		const onPopState = () => {
			const view = page.state.view ?? parseUrl();
			if (!view) return;
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

	onDestroy(() => {
		renderer?.dispose();
	});
</script>

<div class="relative w-full h-full">
	<canvas bind:this={canvas} class="w-full h-full block"></canvas>
	<div bind:this={labelContainer} class="absolute inset-0 pointer-events-none z-0"></div>
</div>
