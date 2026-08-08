<!--
  The launch-window field: total Δv over departure date against cruise length,
  with the chosen route marked.

  Given an `onPick` it also becomes the way to fly something the solver did not
  offer: any point on the field is a departure date and a cruise length, and
  those are the whole of a trajectory.

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
		/** Given a departure date and cruise length read off the field. Without it
		 *  the chart is a picture rather than a control. */
		onPick?: ((departJd: number, tofDays: number) => void) | null;
	}
	let { grid, route = null, height = 190, colormap = 'viridis', onPick = null }: Props = $props();

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

	// What each axis covers. Null when one has no extent: such a grid still draws,
	// but nothing can be placed on it or read off it.
	let spans = $derived.by(() => {
		if (grid.departSteps < 2 || grid.tofSteps < 2) return null;
		const depart = grid.departJds[grid.departSteps - 1] - grid.departJds[0];
		const tof = grid.tofDays[grid.tofSteps - 1] - grid.tofDays[0];
		return depart > 0 && tof > 0 ? { depart, tof } : null;
	});

	/** Where the chosen route sits on the field, as fractions of each axis. */
	let mark = $derived.by(() => {
		if (!route || !spans) return null;
		// Held to the edges rather than dropped: the cheapest route sits on one
		// often enough that a hair of rounding there would take the mark off the
		// chart entirely.
		return {
			x: clamp01((route.departJd - grid.departJds[0]) / spans.depart),
			y: clamp01((route.tofDays - grid.tofDays[0]) / spans.tof)
		};
	});

	function clamp(value: number, lo: number, hi: number): number {
		return value < lo ? lo : value > hi ? hi : value;
	}

	function clamp01(value: number): number {
		return clamp(value, 0, 1);
	}

	let plot = $state<HTMLElement | null>(null);
	let field = $state<HTMLButtonElement | null>(null);
	// Set when a press already picked, so the click it turns into does not pick a
	// second time.
	let pressPicked = false;

	/** Hand the field the focus, for the empty row in the list that points here. */
	export function focusField(): void {
		field?.focus();
	}

	/** Take the point under a pointer. The mark's own inset is undone here, so the
	 *  dot lands where the cursor is rather than a few pixels inside it. */
	function pickAt(clientX: number, clientY: number): void {
		if (!plot || !spans || !onPick) return;
		const box = plot.getBoundingClientRect();
		const fx = clamp01((clientX - box.left - DOT_RADIUS_PX) / (box.width - DOT_RADIUS_PX * 2));
		const fy = clamp01((clientY - box.top - DOT_RADIUS_PX) / (box.height - DOT_RADIUS_PX * 2));
		onPick(grid.departJds[0] + fx * spans.depart, grid.tofDays[0] + fy * spans.tof);
	}

	// The cruise axis runs shortest at the top, so up is the faster arc.
	const ARROW_STEPS: Record<string, [number, number]> = {
		ArrowLeft: [-1, 0],
		ArrowRight: [1, 0],
		ArrowUp: [0, -1],
		ArrowDown: [0, 1]
	};

	/** Walk the mark a cell at a time, so the field can be picked from without a
	 *  pointer. With nothing marked yet the walk starts at the middle. */
	function nudge(event: KeyboardEvent): void {
		const step = ARROW_STEPS[event.key];
		if (!step || !spans || !onPick) return;
		event.preventDefault();
		const departFromJd = grid.departJds[0];
		const departToJd = grid.departJds[grid.departSteps - 1];
		const tofMin = grid.tofDays[0];
		const tofMax = grid.tofDays[grid.tofSteps - 1];
		const depart = route?.departJd ?? departFromJd + spans.depart / 2;
		const tof = route?.tofDays ?? tofMin + spans.tof / 2;
		onPick(
			clamp(depart + (step[0] * spans.depart) / (grid.departSteps - 1), departFromJd, departToJd),
			clamp(tof + (step[1] * spans.tof) / (grid.tofSteps - 1), tofMin, tofMax)
		);
	}

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
			bind:this={plot}
			class="border-border/60 relative min-w-0 flex-1 overflow-hidden rounded-md border"
			style="height: {height}px"
		>
			<!-- crispEdges: a cell is under 3px wide, so antialiased edges let the
			     panel behind show through every seam as a dark lattice. -->
			<svg
				viewBox="0 0 {grid.departSteps} {grid.tofSteps}"
				preserveAspectRatio="none"
				shape-rendering="crispEdges"
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
			{#if onPick}
				<!-- The field is picked on, not just read. A transparent overlay takes
				     the pointer so the cells stay plain rects, and arrow keys walk the
				     mark for anyone not using one. -->
				<button
					bind:this={field}
					type="button"
					class="focus:inset-ring-ring absolute inset-0 cursor-crosshair focus:inset-ring-2 focus:outline-none"
					aria-label={m.travel_windows_pick()}
					onpointerdown={(event) => {
						// A finger keeps its gesture: a swipe here should scroll the panel,
						// so touch picks on the tap that follows instead.
						pressPicked = event.pointerType !== 'touch';
						if (!pressPicked) return;
						event.currentTarget.setPointerCapture(event.pointerId);
						pickAt(event.clientX, event.clientY);
					}}
					onpointermove={(event) => {
						if (pressPicked && event.buttons === 1) pickAt(event.clientX, event.clientY);
					}}
					onclick={(event) => {
						// `detail` is 0 for the click a keypress synthesizes, which carries
						// no coordinates and would read as the top-left corner.
						if (!pressPicked && event.detail > 0) pickAt(event.clientX, event.clientY);
					}}
					onkeydown={nudge}
				></button>
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
