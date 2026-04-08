<script lang="ts">
	import { onMount, onDestroy, getContext } from 'svelte';
	import { SceneRenderer } from '$lib/scene/renderer';
	import type { ContextManager } from '$lib/scene/context-manager.svelte';
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

	interface Props {
		initialView: MapViewState;
		onFocusChange?: (body: PositionedBody | undefined) => void;
	}

	let { initialView, onFocusChange }: Props = $props();

	const ctx = getContext<ContextManager>('ctx');

	let canvas: HTMLCanvasElement;
	let labelContainer: HTMLDivElement;
	let renderer: SceneRenderer | undefined;
	let focusedBody = $state<PositionedBody | undefined>();

	export function focusOnBody(id: string, zoom?: number): number {
		return renderer?.focusOnBody(id, zoom) ?? 0;
	}

	let lastCameraPos = {
		latitude: initialView.latitude,
		longitude: initialView.longitude,
		zoom: initialView.zoom
	};

	function syncUrl(latitude: number, longitude: number, zoom: number) {
		lastCameraPos = { latitude, longitude, zoom };
		if (!focusedBody) return;
		writeUrlState({
			type: urlTypeFromId(focusedBody.data.id),
			id: focusedBody.data.id,
			name: focusedBody.data.name ?? '',
			date: initialView.date,
			isNow: initialView.isNow,
			latitude,
			longitude,
			zoom
		});
	}

	let isInitialFocus = true;
	let isNavigatingBack = false;

	onMount(() => {
		renderer = new SceneRenderer(canvas, labelContainer, ctx, initialView, {
			onFocusChange(body) {
				const wasInitial = isInitialFocus;
				isInitialFocus = false;
				focusedBody = body;
				onFocusChange?.(body);
				if (!wasInitial && !isNavigatingBack && body) {
					pushUrlState({
						type: urlTypeFromId(body.data.id),
						id: body.data.id,
						name: body.data.name ?? '',
						date: initialView.date,
						isNow: initialView.isNow,
						...lastCameraPos
					});
				}
			},
			onCameraPosition: syncUrl
		});

		const ro = new ResizeObserver(() => {
			renderer?.resize(canvas.clientWidth, canvas.clientHeight);
		});
		ro.observe(canvas);

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
			ro.disconnect();
			window.removeEventListener('popstate', onPopState);
		};
	});

	$effect(() => {
		void ctx.asteroidBodiesByZone.size; // reactive dependency — re-runs on each flush
		renderer?.rebuildMinorPointClouds();
	});

	onDestroy(() => {
		renderer?.dispose();
	});
</script>

<div class="relative w-full h-full">
	<canvas bind:this={canvas} class="w-full h-full block"></canvas>
	<div bind:this={labelContainer} dir="ltr" class="absolute inset-0 pointer-events-none z-0"></div>
</div>
