<script lang="ts">
	import { onMount, onDestroy, getContext } from 'svelte';
	import { SceneRenderer } from '$lib/scene/renderer';
	import type { ContextManager } from '$lib/scene/context-manager.svelte';
	import type { PositionedBody } from '$lib/types/objects';
	import { type MapViewState, sphericalToCartesian, writeUrlState, parseUrl } from '$lib/url-state';
	import { urlTypeFromId } from '$lib/format';

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

	function syncUrl(latitude: number, longitude: number, zoom: number) {
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

	onMount(() => {
		renderer = new SceneRenderer(canvas, labelContainer, ctx, initialView, {
			onFocusChange(body) {
				focusedBody = body;
				onFocusChange?.(body);
			},
			onCameraPosition: syncUrl
		});

		const ro = new ResizeObserver(() => {
			renderer?.resize(canvas.clientWidth, canvas.clientHeight);
		});
		ro.observe(canvas);

		const onPopState = () => {
			const parsed = parseUrl();
			if (!parsed) return;
			const body = ctx.allBodies.find((b) => b.data.id === parsed.id);
			const target = body?.position ?? renderer?.getFocusedBody()?.position ?? [0, 0, 0];
			const camPos = sphericalToCartesian(target, parsed.latitude, parsed.longitude, parsed.zoom);
			if (body) renderer?.setFocusTarget(body, camPos);
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
