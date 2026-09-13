<!--
  The traverse on a flat map of the body, bottom left of the viewer: driven
  path in white, the rest in grey, and a wedge for where the reader is looking.
  Small by default; the expand button grows it and opens the timeline.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { fade } from 'svelte/transition';
	import Maximize2Icon from '@lucide/svelte/icons/maximize-2';
	import Minimize2Icon from '@lucide/svelte/icons/minimize-2';
	import * as m from '$lib/paraglide/messages.js';
	import type { PanoramaEntry } from '$lib/fetch/objects/object-data';
	import { FlatMap } from '$lib/flatmap/flat-map';
	import type { FlatMarker, FlatShape } from '$lib/flatmap/overlay';
	import type { LayerCredit } from '$lib/flatmap/layers';
	import { formatKm } from '$lib/format/distance';
	import { lonLatOf, scaleBar, splitPath, traverseFrame, viewWedge } from '$lib/panorama/minimap';

	interface Props {
		bodyId: string;
		/** The mission's panoramas in traverse order. */
		entries: readonly PanoramaEntry[];
		current: PanoramaEntry;
		/** Mean radius of the body, kilometres; sizes the scale bar. */
		radiusKm: number;
		/** The clock the path is split at. */
		jd: number;
		headingDeg: number;
		fovDeg: number;
		expanded: boolean;
		/** Height to grow to when expanded, pixels; the box animates to it. */
		height: number | null;
		onToggle: () => void;
		/** Who the map's layers are credited to, whenever that changes. */
		onCredits: (credits: LayerCredit[]) => void;
		onPick: (entry: PanoramaEntry) => void;
	}

	let {
		bodyId,
		entries,
		current,
		radiusKm,
		jd,
		headingDeg,
		fovDeg,
		expanded,
		height,
		onToggle,
		onCredits,
		onPick
	}: Props = $props();

	/** A traverse of a few hundred metres still gets a frame this wide. */
	const MIN_SPAN_DEG = 0.02;
	/** How close a click must land to a panorama, in screen pixels. */
	const PICK_PX = 14;

	let container: HTMLElement;
	let map = $state<FlatMap | null>(null);
	/** The drawings, made once the map is up and moved from then on. */
	let drawn = $state.raw<{
		past: FlatShape;
		future: FlatShape;
		wedge: FlatShape;
		here: FlatMarker;
	} | null>(null);
	let scale = $state<{ px: number; label: string } | null>(null);

	onMount(() => {
		const flat = new FlatMap({
			body: bodyId,
			projection: 'orthographic',
			interactive: false,
			layers: { clouds: false, night: false }
		});
		flat.mount(container);
		flat.on('click', (at) => {
			if (!at) return;
			const here = flat.project(at.lon, at.lat);
			if (!here) return;
			let best: PanoramaEntry | null = null;
			let bestPx = PICK_PX;
			for (const entry of entries) {
				const px = flat.project(entry.lon, entry.lat);
				if (!px) continue;
				const d = Math.hypot(px[0] - here[0], px[1] - here[1]);
				if (d < bestPx) {
					best = entry;
					bestPx = d;
				}
			}
			if (best) onPick(best);
			else onToggle();
		});
		flat.once('ready', () => {
			map = flat;
			onCredits(flat.credits);
		});
		flat.on('layerschange', () => onCredits(flat.credits));
		flat.on('error', (error) => console.warn('Minimap:', error));
		void flat.load();
		// The box changes shape as the timeline opens and closes; the frame
		// follows it.
		const observer = new ResizeObserver(() => frame());
		observer.observe(container);
		return () => {
			observer.disconnect();
			flat.remove();
			map = null;
		};
	});

	/** Hold the whole traverse in the box, whatever the projection. */
	function frame(): void {
		if (!map) return;
		const box = traverseFrame(entries, MIN_SPAN_DEG);
		map.setView({ zoom: 1, centerLon: box.centerLon, centerLat: box.centerLat });
		const a = map.project(box.centerLon - box.lonSpan / 2, box.centerLat - box.latSpan / 2);
		const b = map.project(box.centerLon + box.lonSpan / 2, box.centerLat + box.latSpan / 2);
		if (!a || !b) return;
		const { clientWidth: w, clientHeight: h } = container;
		if (!w || !h) return;
		map.setView({ zoom: Math.min(w / Math.abs(b[0] - a[0]), h / Math.abs(b[1] - a[1])) });
		const up = map.project(box.centerLon, box.centerLat + 0.01);
		const at = map.project(box.centerLon, box.centerLat);
		const pxPerDeg = up && at ? Math.abs(up[1] - at[1]) / 0.01 : 0;
		if (!radiusKm || !pxPerDeg) {
			scale = null;
			return;
		}
		const bar = scaleBar((radiusKm * 1000 * Math.PI) / 180 / pxPerDeg, w / 3);
		scale = { px: bar.px, label: formatKm(bar.metres / 1000) };
	}

	$effect(() => {
		void entries;
		void radiusKm;
		frame();
	});

	$effect(() => {
		if (!map) return;
		const d = {
			future: map.addPolyline({ points: [], color: '#9ca3af', widthPx: 2, opacity: 0.9 }),
			past: map.addPolyline({ points: [], color: '#ffffff', widthPx: 2 }),
			wedge: map.addPolygon({
				points: [],
				color: '#facc15',
				widthPx: 1,
				opacity: 0.9,
				fill: '#facc15',
				fillOpacity: 0.3
			}),
			here: map.addMarker({ at: lonLatOf(current), className: 'panorama-minimap-here' })
		};
		drawn = d;
		return () => {
			for (const shape of Object.values(d)) shape.remove();
			drawn = null;
		};
	});

	$effect(() => {
		if (!drawn) return;
		const { past, future } = splitPath(entries, jd);
		drawn.past.setPoints(past);
		drawn.future.setPoints(future);
	});

	/** How far the wedge reaches, in degrees of latitude: far past what a
	 *  camera sees, so it still reads at the scale of the whole traverse. */
	const reach = $derived(traverseFrame(entries, MIN_SPAN_DEG).latSpan * 0.2);

	$effect(() => {
		drawn?.wedge.setPoints(viewWedge(current, headingDeg, fovDeg, reach));
	});

	$effect(() => {
		drawn?.here.setPosition(lonLatOf(current));
	});
</script>

<div
	class="relative overflow-hidden rounded-md bg-black/40 backdrop-blur-sm transition-[width,height] duration-250 ease-out motion-reduce:transition-none"
	style="width: {expanded ? '20rem' : '11rem'}; height: {expanded && height
		? `${height}px`
		: '7rem'}"
	role="img"
	aria-label={m.panorama_map_label()}
>
	<div bind:this={container} class="absolute inset-0 cursor-pointer"></div>
	<span
		class="pointer-events-none absolute top-1 start-1.5 text-[10px] font-semibold text-white/70"
		aria-hidden="true">N ↑</span
	>
	{#if expanded && scale}
		<div
			class="pointer-events-none absolute bottom-1.5 start-1.5 text-[10px] leading-tight text-white/80"
			aria-hidden="true"
			transition:fade={{ duration: 150 }}
		>
			<div class="h-1.5 border-x border-b border-white/80" style="width: {scale.px}px"></div>
			{scale.label}
		</div>
	{/if}
	<button
		type="button"
		onclick={onToggle}
		class="absolute top-1 end-1 hidden size-6 cursor-pointer items-center justify-center rounded bg-black/50 text-white hover:bg-black/70 md:flex"
		aria-label={expanded ? m.panorama_map_collapse() : m.panorama_map_expand()}
		title={expanded ? m.panorama_map_collapse() : m.panorama_map_expand()}
		aria-expanded={expanded}
	>
		{#if expanded}
			<Minimize2Icon class="size-3.5" />
		{:else}
			<Maximize2Icon class="size-3.5" />
		{/if}
	</button>
</div>

<style>
	:global(.panorama-minimap-here) {
		width: 8px;
		height: 8px;
		border-radius: 9999px;
		background: #facc15;
		box-shadow: 0 0 0 1.5px #000;
	}
</style>
