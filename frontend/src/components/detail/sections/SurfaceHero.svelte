<script lang="ts">
	/** The Surface tab's hero: the body's map texture, with a marker for the
	 *  feature the list is hovering. Bodies on an IAU quadrangle grid also get
	 *  their charts drawn over it — clicking one zooms the map onto it and
	 *  narrows the list. Cells are keyboard-reachable through a single tab stop
	 *  with arrow keys walking them (144 charts on the Moon). */

	import { untrack } from 'svelte';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import * as m from '$lib/paraglide/messages.js';
	import { versionedUrl } from '$lib/fetch/data-base';
	import { formatCompactNumber } from '$lib/format/quantities';
	import { fetchBodyNomenclature } from '$lib/fetch/nomenclature/fetch';
	import type { Quadrangle } from '$lib/fetch/nomenclature/quadrangles';

	interface Props {
		bodyId: string;
		/** Empty for bodies with no IAU chart grid — then it's just the map. */
		quads: Quadrangle[];
		selected: string | null;
		onselect: (code: string | null) => void;
		/** IAU id of the feature the list is hovering, marked on the map. */
		markedFeatureId?: number | null;
	}
	let { bodyId, quads, selected, onselect, markedFeatureId = null }: Props = $props();

	/** Beyond this the low-tier map (2048 px wide) turns to mush; a small
	 *  quadrangle stays centred rather than filling the frame. */
	const MAX_ZOOM = 4;

	// Canonical equirect mapping: u = (lon + 180) / 360, east-positive. The
	// viewBox is degrees, so x is that in 0–360 and y is 90 − lat.
	const xOf = (lonEast: number) => (lonEast + 180) % 360;

	interface Cell extends Quadrangle {
		/** One rect normally, two for a cell straddling the map's edge. */
		rects: { x: number; y: number; w: number; h: number }[];
		cx: number;
		cy: number;
	}

	let cells = $derived(
		quads.map((q): Cell => {
			const x = xOf(q.lon_min);
			const y = 90 - q.lat_max;
			const h = q.lat_max - q.lat_min;
			const overflow = x + q.lon_span - 360;
			// A polar cap covers every longitude — one rect across the map, not
			// two meeting at a seam the wrap branch would otherwise draw.
			const rects =
				q.lon_span >= 360
					? [{ x: 0, y, w: 360, h }]
					: overflow > 0
						? [
								{ x, y, w: 360 - x, h },
								{ x: 0, y, w: overflow, h }
							]
						: [{ x, y, w: q.lon_span, h }];
			// Centre on the widest rect: a cell split across the map's edge can't
			// be framed whole, so zoom onto its larger half.
			const main = rects.reduce((a, b) => (b.w > a.w ? b : a));
			return { ...q, rects, cx: main.x + main.w / 2, cy: y + h / 2 };
		})
	);

	let active = $derived(cells.find((c) => c.code === selected) ?? null);

	// Zoom so the selected cell fills the frame, capped. Fractions of the map.
	let view = $derived.by(() => {
		if (!active) return { scale: 1, tx: 0, ty: 0 };
		const wFrac = active.lon_span / 360;
		const hFrac = (active.lat_max - active.lat_min) / 180;
		const scale = Math.min(MAX_ZOOM, 1 / wFrac, 1 / hFrac);
		// Clamped so the map always covers the frame — no gutters when a cell
		// sits against an edge.
		const pan = (centre: number, span: number) =>
			Math.min(0, Math.max(1 - scale, 0.5 - (centre / span) * scale));
		return { scale, tx: pan(active.cx, 360), ty: pan(active.cy, 180) };
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
	let marker = $derived.by(() => {
		const at = markedFeatureId != null ? positions.get(markedFeatureId) : undefined;
		return at ? { x: xOf(at.lon), y: 90 - at.lat } : null;
	});

	let mapFailed = $state(false);
	let mapUrl = $derived(versionedUrl(`/v1/textures/${bodyId}/low.webp`, 'textures'));
</script>

<div class="flex flex-col gap-1.5">
	<div
		class="border-border/60 bg-muted/30 relative aspect-2/1 w-full overflow-hidden rounded-lg border"
	>
		<div
			class="absolute inset-0 origin-top-left transition-transform duration-500 ease-out"
			style="transform: translate({view.tx * 100}%, {view.ty * 100}%) scale({view.scale})"
		>
			{#if !mapFailed}
				<img
					src={mapUrl}
					alt=""
					loading="lazy"
					decoding="async"
					onerror={() => (mapFailed = true)}
					class="absolute inset-0 size-full object-fill"
				/>
			{/if}
			<svg
				viewBox="0 0 360 180"
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
						class="cursor-pointer outline-none focus-visible:[&>rect]:stroke-[3px]"
						onclick={() => onselect(on ? null : cell.code)}
						onkeydown={(e) => onKey(e, i)}
						onmouseenter={() => (hovered = cell.code)}
						onmouseleave={() => (hovered = null)}
					>
						<!-- `non-scaling-stroke` cancels the viewBox scale but not the CSS
						     transform above it, so the zoom is divided back out to keep the
						     borders a constant width. -->
						{#each cell.rects as r, j (j)}
							<rect
								x={r.x}
								y={r.y}
								width={r.w}
								height={r.h}
								vector-effect="non-scaling-stroke"
								class="transition-colors {on
									? 'fill-transparent stroke-primary'
									: selected
										? 'fill-black/45 stroke-white/20 hover:fill-black/25'
										: 'fill-transparent stroke-white/25 hover:fill-white/15'}"
								stroke-width={(on ? 2.5 : 1) / view.scale}
							/>
						{/each}
					</g>
				{/each}
				{#if marker}
					<!-- Constant on-screen size: radii and stroke divide the zoom back
					     out, and the viewBox is 2:1 stretched so x/y radii differ. -->
					<ellipse
						cx={marker.x}
						cy={marker.y}
						rx={5 / view.scale}
						ry={2.5 / view.scale}
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
			<button
				type="button"
				class="text-muted-foreground hover:text-foreground transition-colors"
				onclick={() => onselect(null)}>{m.feature_quadrangle_all()}</button
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
