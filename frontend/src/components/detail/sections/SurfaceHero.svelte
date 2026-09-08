<script lang="ts">
	/** The Surface tab's hero: the body's map texture, with a marker for the
	 *  feature the list is hovering. Bodies on an IAU quadrangle grid also get
	 *  their charts drawn over it — clicking one zooms the map onto it and
	 *  narrows the list. Cells are keyboard-reachable through a single tab stop
	 *  with arrow keys walking them (144 charts on the Moon).
	 *
	 *  The geometry goes through the flat map's projections, so the same hero
	 *  draws in any of them. Equirectangular is the texture's own space and
	 *  needs no resampling, so it stays an image; anything else is redrawn into
	 *  a canvas. */

	import { getContext, untrack } from 'svelte';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import * as m from '$lib/paraglide/messages.js';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { quadHref } from '$lib/state/focus-link';
	import { isModifiedClick } from '$lib/modified-click';
	import { versionedUrl } from '$lib/fetch/data-base';
	import { formatCompactNumber } from '$lib/format/quantities';
	import { fetchBodyNomenclature } from '$lib/fetch/nomenclature/fetch';
	import type { Quadrangle } from '$lib/fetch/nomenclature/quadrangles';
	import { boxRing, densify, pathFor } from '$lib/flatmap/geometry';
	import { createProjection, projectionAspect, type ProjectionId } from '$lib/flatmap/projection';
	import { drawStill } from '$lib/flatmap/raster';
	import { Viewport } from '$lib/flatmap/view';

	interface Props {
		bodyId: string;
		/** Empty for bodies with no IAU chart grid — then it's just the map. */
		quads: Quadrangle[];
		selected: string | null;
		onselect: (code: string | null) => void;
		/** IAU id of the feature the list is hovering, marked on the map. */
		markedFeatureId?: number | null;
		/** How the globe is laid flat. The texture's own space by default, which
		 *  is what the tab has always shown. */
		projection?: ProjectionId;
	}
	let {
		bodyId,
		quads,
		selected,
		onselect,
		markedFeatureId = null,
		projection = 'equirectangular'
	}: Props = $props();

	const appState = getContext<AppState | undefined>('appState');

	function selectAll(e: MouseEvent) {
		if (isModifiedClick(e)) return;
		e.preventDefault();
		onselect(null);
	}

	/** Beyond this the low-tier map (2048 px wide) turns to mush; a small
	 *  quadrangle stays centred rather than filling the frame. */
	const MAX_ZOOM = 4;

	/** The overlay's own coordinates. Wide enough that a rounded path keeps its
	 *  precision, and shaped by the projection so units stay square. */
	const VIEW_W = 720;

	let projected = $derived(createProjection(projection));
	let aspect = $derived(projectionAspect(projected));
	let viewH = $derived(VIEW_W / aspect);
	let viewport = $derived(
		new Viewport(projected, VIEW_W, viewH, { zoom: 1, centerX: 0, centerY: 0 })
	);

	interface Cell extends Quadrangle {
		/** The cell's outline in overlay coordinates, already broken where it
		 *  crosses the seam or leaves the map. */
		d: string;
		/** Where the cell sits, for framing it when it is picked. */
		box: { x: number; y: number; w: number; h: number } | null;
	}

	let cells = $derived(
		quads.map((q): Cell => {
			const ring = boxRing(q.lat_min, q.lat_max, q.lon_min, q.lon_span);
			// The framing box comes from the projected outline, not the degrees:
			// a cell is a different shape in every projection, and on a globe part
			// of it may not be on the map at all.
			let minX = Infinity;
			let minY = Infinity;
			let maxX = -Infinity;
			let maxY = -Infinity;
			for (const point of densify(ring, { closed: true })) {
				const at = viewport.project(point.lon, point.lat);
				if (!at) continue;
				minX = Math.min(minX, at[0]);
				maxX = Math.max(maxX, at[0]);
				minY = Math.min(minY, at[1]);
				maxY = Math.max(maxY, at[1]);
			}
			const box =
				minX === Infinity
					? null
					: { x: minX, y: minY, w: Math.max(1, maxX - minX), h: Math.max(1, maxY - minY) };
			return { ...q, d: pathFor(ring, viewport, { closed: true }), box };
		})
	);

	let active = $derived(cells.find((c) => c.code === selected) ?? null);

	// Zoom so the selected cell fills the frame, capped. Fractions of the map.
	let view = $derived.by(() => {
		if (!active?.box) return { scale: 1, tx: 0, ty: 0 };
		const { x, y, w, h } = active.box;
		const scale = Math.min(MAX_ZOOM, VIEW_W / w, viewH / h);
		// Clamped so the map always covers the frame — no gutters when a cell
		// sits against an edge.
		const pan = (centre: number, span: number) =>
			Math.min(0, Math.max(1 - scale, 0.5 - (centre / span) * scale));
		return { scale, tx: pan(x + w / 2, VIEW_W), ty: pan(y + h / 2, viewH) };
	});

	let hovered = $state<string | null>(null);
	let caption = $derived(cells.find((c) => c.code === (hovered ?? selected)) ?? null);

	// Roving tab stop: one entry into the grid, arrows walk it in code order.
	let cursor = $state(0);
	$effect(() => {
		const i = cells.findIndex((c) => c.code === selected);
		if (i >= 0) cursor = i;
	});

	function onKey(event: KeyboardEvent, index: number) {
		const step =
			event.key === 'ArrowRight' || event.key === 'ArrowDown'
				? 1
				: event.key === 'ArrowLeft' || event.key === 'ArrowUp'
					? -1
					: 0;
		if (step) {
			event.preventDefault();
			cursor = (index + step + cells.length) % cells.length;
			(event.currentTarget as SVGGElement)
				.closest('svg')
				?.querySelector<SVGGElement>(`[data-idx="${cursor}"]`)
				?.focus();
			return;
		}
		if (event.key === 'Enter' || event.key === ' ') {
			event.preventDefault();
			onselect(cells[index].code === selected ? null : cells[index].code);
		}
	}

	// Positions for the hovered marker. Same file the surface labels use, so it
	// is usually already cached by the time the drawer opens.
	let positions = $state<Map<number, { lat: number; lon: number }>>(new Map());
	$effect(() => {
		const id = bodyId;
		let live = true;
		untrack(() => fetchBodyNomenclature(id)).then((feats) => {
			if (!live) return;
			positions = new Map(feats.map((f) => [f.featureId, { lat: f.lat, lon: f.lon }]));
		});
		return () => {
			live = false;
		};
	});
	/** Marker radius in overlay units before the zoom is divided out. */
	const MARKER_R = 7;

	let marker = $derived.by(() => {
		const at = markedFeatureId != null ? positions.get(markedFeatureId) : undefined;
		if (!at) return null;
		const screen = viewport.project(at.lon, at.lat);
		// A feature on the far side of a globe projection has nowhere to be marked.
		if (!screen) return null;
		const { scale, tx, ty } = view;
		const r = MARKER_R / scale;
		// Held inside the visible window, so a feature outside the zoomed-in
		// chart still shows which way it lies instead of vanishing.
		const clamp = (v: number, offset: number, span: number) => {
			const min = (-offset / scale) * span;
			return Math.min(Math.max(v, min + r), min + span / scale - r);
		};
		return { x: clamp(screen[0], tx, VIEW_W), y: clamp(screen[1], ty, viewH), r };
	});

	let mapFailed = $state(false);
	let mapUrl = $derived(versionedUrl(`/v1/textures/${bodyId}/low.webp`, 'textures'));

	// Every projection but the texture's own has to be resampled, which needs
	// the picture as pixels rather than an <img> the browser places for us.
	let canvas = $state<HTMLCanvasElement | null>(null);
	$effect(() => {
		const url = mapUrl;
		const target = canvas;
		const frame = viewport;
		if (!target || projection === 'equirectangular') return;
		let live = true;
		fetch(url)
			.then((response) => (response.ok ? response.blob() : Promise.reject(response.status)))
			.then((blob) => createImageBitmap(blob))
			.then((bitmap) => {
				if (!live) {
					bitmap.close();
					return;
				}
				// Drawn at twice the overlay's own width: the frame is zoomed by CSS,
				// so the backing store carries the detail that zoom reveals.
				drawStill(
					target,
					new Viewport(frame.projection, VIEW_W * 2, frame.height * 2, frame.view),
					[{ image: bitmap, opacity: 1, blend: 'normal' }]
				);
				bitmap.close();
			})
			.catch(() => {
				if (live) mapFailed = true;
			});
		return () => {
			live = false;
		};
	});
</script>

<div class="flex flex-col gap-1.5">
	<div
		class="border-border/60 bg-muted/30 relative w-full overflow-hidden rounded-lg border"
		style="aspect-ratio: {aspect}"
	>
		<div
			class="absolute inset-0 origin-top-left transition-transform duration-500 ease-out"
			style="transform: translate({view.tx * 100}%, {view.ty * 100}%) scale({view.scale})"
		>
			{#if !mapFailed}
				{#if projection === 'equirectangular'}
					<img
						src={mapUrl}
						alt=""
						loading="lazy"
						decoding="async"
						onerror={() => (mapFailed = true)}
						class="absolute inset-0 size-full object-fill"
					/>
				{:else}
					<canvas bind:this={canvas} class="absolute inset-0 size-full"></canvas>
				{/if}
			{/if}
			<svg
				viewBox="0 0 {VIEW_W} {viewH}"
				preserveAspectRatio="none"
				class="absolute inset-0 size-full"
				role="group"
				aria-label={m.feature_quadrangle_map()}
			>
				{#each cells as cell, i (cell.code)}
					{@const on = cell.code === selected}
					<g
						role="button"
						tabindex={i === cursor ? 0 : -1}
						data-idx={i}
						aria-pressed={on}
						aria-label={m.feature_quadrangle_cell({
							name: cell.name,
							count: formatCompactNumber(cell.n)
						})}
						class="cursor-pointer outline-none focus-visible:[&>path]:stroke-[3px]"
						onclick={() => onselect(on ? null : cell.code)}
						onkeydown={(e) => onKey(e, i)}
						onmouseenter={() => (hovered = cell.code)}
						onmouseleave={() => (hovered = null)}
					>
						<!-- `non-scaling-stroke` cancels the viewBox scale but not the CSS
						     transform above it, so the zoom is divided back out to keep the
						     borders a constant width. -->
						<path
							d={cell.d}
							vector-effect="non-scaling-stroke"
							class="transition-colors {on
								? 'fill-transparent stroke-primary'
								: selected
									? 'fill-black/45 stroke-white/20 hover:fill-black/25'
									: 'fill-transparent stroke-white/25 hover:fill-white/15'}"
							stroke-width={(on ? 2.5 : 1) / view.scale}
						/>
					</g>
				{/each}
				{#if marker}
					<!-- Constant on-screen size: the radius divides the zoom back out.
					     The viewBox matches the frame's shape, so units are square and a
					     circle stays round. -->
					<circle
						cx={marker.x}
						cy={marker.y}
						r={marker.r}
						class="fill-primary/30 stroke-primary"
						stroke-width={2 / view.scale}
						vector-effect="non-scaling-stroke"
					/>
				{/if}
			</svg>
		</div>
	</div>

	<!-- One row, always the same height: the selected chart with its way back
	     out, or — while the pointer is over another cell — that cell as a
	     preview, since a crumb pointing at something unselected would lie. -->
	<div class="flex min-h-5 items-baseline gap-1.5 text-xs">
		{#if selected && caption?.code === selected}
			<a
				href={quadHref(appState, null)}
				class="text-muted-foreground hover:text-foreground transition-colors"
				onclick={selectAll}>{m.feature_quadrangle_all()}</a
			>
			<ChevronRightIcon class="text-muted-foreground size-3 self-center rtl:rotate-180" />
		{/if}
		{#if caption}
			<span class="truncate font-medium">{caption.name}</span>
			<span class="text-muted-foreground tabular-nums">
				{m.feature_quadrangle_count({ count: formatCompactNumber(caption.n) })}
			</span>
		{/if}
	</div>
</div>
