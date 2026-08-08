<!--
  The launch-window field: total Δv over departure date against cruise length,
  with the chosen route marked.

  Given room to be read rather than glanced at — the shape of a transfer window
  is two axes of structure, and at thumbnail height the cheap basin collapses
  into a stripe. Both axes are labelled at their ends, so a reader can place the
  mark without a full axis apparatus in a 390px column.

  Colour is viridis: a porkchop is a continuous field, and a perceptually
  uniform map is the one that doesn't invent contour bands where the data is
  smooth.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import type { PorkchopGrid, Route } from '$lib/math/travel';
	import { formatJulianDate } from '$lib/format/date';
	import { gradient, sample, type ColormapName } from '$lib/travel/colormap';
	import { formatTripTime } from '$lib/travel/format';

	interface Props {
		grid: PorkchopGrid;
		/** Marked on the field; omitted when nothing is chosen. */
		route?: Route | null;
		height?: number;
		colormap?: ColormapName;
	}
	let { grid, route = null, height = 190, colormap = 'viridis' }: Props = $props();

	/** Half the marker dot, ring included — how far it must sit off each edge. */
	const DOT_RADIUS_PX = 6;

	// The scale spans the solved cells only: an unsolved corner would otherwise
	// stretch the ramp and flatten every real difference into one step.
	let bounds = $derived.by(() => {
		let min = Infinity;
		let max = -Infinity;
		for (const dv of grid.totalDvKms) {
			if (!Number.isFinite(dv)) continue;
			if (dv < min) min = dv;
			if (dv > max) max = dv;
		}
		return { min, max, span: max - min || 1 };
	});

	// Cheap reads as the bright end. Viridis runs dark → bright, and a launch
	// window is the thing you are looking *for*, so it should be what glows.
	function fill(dv: number): string {
		if (!Number.isFinite(dv)) return 'transparent';
		return sample(colormap, 1 - (dv - bounds.min) / bounds.span);
	}

	/** Where the chosen route sits on the field, as fractions of each axis. */
	let mark = $derived.by(() => {
		if (!route || grid.departSteps < 2 || grid.tofSteps < 2) return null;
		const departSpan = grid.departJds[grid.departSteps - 1] - grid.departJds[0];
		const tofSpan = grid.tofDays[grid.tofSteps - 1] - grid.tofDays[0];
		if (!(departSpan > 0) || !(tofSpan > 0)) return null;
		const x = (route.departJd - grid.departJds[0]) / departSpan;
		const y = (route.tofDays - grid.tofDays[0]) / tofSpan;
		// Held to the edges rather than dropped: the cheapest route sits on one
		// often enough that a hair of rounding there would take the mark off the
		// chart entirely.
		return { x: Math.min(Math.max(x, 0), 1), y: Math.min(Math.max(y, 0), 1) };
	});

	let departFrom = $derived(formatJulianDate(grid.departJds[0]));
	let departTo = $derived(formatJulianDate(grid.departJds[grid.departSteps - 1]));
	let tofShort = $derived(formatTripTime(grid.tofDays[0]));
	let tofLong = $derived(formatTripTime(grid.tofDays[grid.tofSteps - 1]));
</script>

<figure class="flex flex-col gap-1.5">
	<div class="flex gap-1.5">
		<!-- Cruise length runs bottom-to-top, so its end labels sit beside the
		     rows they belong to rather than under a rotated axis title. -->
		<div
			class="text-muted-foreground flex shrink-0 flex-col justify-between text-end text-[10px] leading-none"
		>
			<span>{tofShort}</span>
			<span class="text-muted-foreground/70">{m.travel_tof_axis()}</span>
			<span>{tofLong}</span>
		</div>

		<div
			class="border-border/60 relative min-w-0 flex-1 overflow-hidden rounded-md border"
			style="height: {height}px"
		>
			<svg
				viewBox="0 0 {grid.departSteps} {grid.tofSteps}"
				preserveAspectRatio="none"
				class="block h-full w-full"
				role="img"
				aria-label={m.travel_windows_alt()}
			>
				{#each { length: grid.departSteps }, i (i)}
					{#each { length: grid.tofSteps }, j (j)}
						<rect
							x={i}
							y={j}
							width="1"
							height="1"
							fill={fill(grid.totalDvKms[i * grid.tofSteps + j])}
						/>
					{/each}
				{/each}
			</svg>
			{#if mark}
				<!-- Ringed in the surface colour so it stays legible on any cell. Inset
				     by its own radius: the cheapest window often sits on an edge, and the
				     clipped half-dot there reads as a different mark. -->
				<span
					class="ring-background pointer-events-none absolute size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white ring-2"
					style="left: calc({DOT_RADIUS_PX}px + {mark.x} * (100% - {DOT_RADIUS_PX * 2}px));
						top: calc({DOT_RADIUS_PX}px + {mark.y} * (100% - {DOT_RADIUS_PX * 2}px))"
				></span>
			{/if}
		</div>
	</div>

	<figcaption class="text-muted-foreground flex flex-col gap-1 text-[10px]">
		<div class="flex items-baseline justify-between gap-2 tabular-nums">
			<span class="truncate">{departFrom}</span>
			<span class="text-muted-foreground/70 shrink-0">{m.travel_departure_axis()}</span>
			<span class="truncate">{departTo}</span>
		</div>
		<div class="flex items-center justify-end gap-1">
			<span>{m.travel_window_cheap()}</span>
			<span
				class="border-border/60 h-2 w-14 rounded-[2px] border"
				style="background: {gradient(colormap, 'left')}"
			></span>
			<span>{m.travel_window_costly()}</span>
		</div>
	</figcaption>
</figure>
