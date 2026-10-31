<script lang="ts">
	/**
	 * One chart of the Planets page on log axes: every planet a dot, a minimum
	 * mass a ring, the Solar System's planets named and linked to their pages.
	 */
	import { getContext } from 'svelte';
	import { scaleLog } from 'd3-scale';
	import * as m from '$lib/paraglide/messages.js';
	import { ltrIsolate } from '$lib/format/bidi';
	import { formatNumber, formatUnit, joinParts, sigFigures, ucfirst } from '$lib/format/quantities';
	import {
		logDomain,
		logExtent,
		logTicks,
		placeLabels,
		powerOfTenLabel,
		PLANET_PLOT_COLORS,
		type PlanetPlotKind,
		type PlanetPlotPoints,
		type PlotPoint
	} from '$lib/charts/planet-plot';
	import { createScrub } from '$lib/charts/scrub';
	import { scatterTooltipLeft, SCATTER_TOOLTIP_MAX_W } from '$lib/charts/scatter-tooltip';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { focusClick, focusHref } from '$lib/state/focus-link';
	import ScatterAxes from './ScatterAxes.svelte';

	interface Props {
		points: PlanetPlotPoints;
		kind: PlanetPlotKind;
		/** Localized names of the Solar System planets, by object id. */
		names: Record<string, string>;
		ariaLabel: string;
		height?: number;
	}

	let { points, kind, names, ariaLabel, height = 240 }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	const M = { top: 8, right: 10, bottom: 32, left: 40 };
	const DOT = 3;
	const RING = 1.8;
	const SOLAR = 3.5;
	const LABEL_FONT = 10;
	// The pick radius around a dot, squared: the size of a finger.
	const PICK_R2 = 12 * 12;

	let width = $state(0);
	let innerW = $derived(Math.max(0, width - M.left - M.right));
	let innerH = $derived(Math.max(0, height - M.top - M.bottom));

	let all = $derived([...points.measured, ...points.minimum, ...points.solar]);
	let xExtent = $derived(logExtent(all.map((p) => p.x)));
	let yExtent = $derived(logExtent(all.map((p) => p.y)));
	let xScale = $derived(scaleLog().domain(logDomain(xExtent, innerW)).range([0, innerW]));
	let yScale = $derived(scaleLog().domain(logDomain(yExtent, innerH)).range([innerH, 0]));
	// The ticks span the values, so no tick falls in the pad.
	let xTicks = $derived(logTicks(xExtent));
	let yTicks = $derived(logTicks(yExtent, 5));

	function formatTick(v: number): string {
		return powerOfTenLabel(v) ?? formatNumber(v);
	}

	type Pixel = { px: number; py: number };
	const toPixel = (p: PlotPoint): Pixel => ({ px: xScale(p.x), py: yScale(p.y) });
	let measured = $derived(points.measured.map(toPixel));
	let minimum = $derived(points.minimum.map(toPixel));
	let solar = $derived(
		points.solar.map((p) => ({ ...p, ...toPixel(p), name: names[p.id] ?? p.id }))
	);

	// One path per kind. Each dot is a round cap on a zero-length stroke.
	let measuredPath = $derived(measured.map((d) => `M${d.px},${d.py}h0`).join(''));
	let minimumPath = $derived(
		minimum
			.map(
				(d) =>
					`M${d.px - RING},${d.py}a${RING},${RING} 0 1 0 ${2 * RING},0a${RING},${RING} 0 1 0 ${-2 * RING},0`
			)
			.join('')
	);

	let measure: CanvasRenderingContext2D | null = null;
	function textWidth(text: string): number {
		if (typeof document === 'undefined') return text.length * LABEL_FONT * 0.6;
		measure ??= document.createElement('canvas').getContext('2d');
		if (!measure) return text.length * LABEL_FONT * 0.6;
		measure.font = `500 ${LABEL_FONT}px ${getComputedStyle(document.body).fontFamily}`;
		return measure.measureText(text).width;
	}
	let labels = $derived(
		innerW > 0
			? placeLabels(
					solar.map((s) => ({ px: s.px, py: s.py, width: textWidth(s.name) })),
					innerW,
					innerH,
					{ lineHeight: LABEL_FONT, dotRadius: SOLAR + 1 }
				)
			: []
	);

	type Hit = { kind: 'solar'; index: number } | { kind: 'measured' | 'minimum'; index: number };
	let hit = $state<Hit | null>(null);
	let mouse = $state({ x: 0, y: 0 });
	let containerEl = $state<HTMLDivElement | null>(null);
	// The label boxes are laid out left to right, but under `direction: rtl`
	// the browser swaps start and end, so the anchor swaps back.
	let rtl = $derived(!!containerEl && getComputedStyle(containerEl).direction === 'rtl');
	const MIRRORED = { start: 'end', end: 'start', middle: 'middle' } as const;

	/** The dot nearest the pointer within a finger's reach; the named ones first. */
	function hitAt(clientX: number, clientY: number) {
		if (!containerEl) return;
		const rect = containerEl.getBoundingClientRect();
		mouse = { x: clientX - rect.left, y: clientY - rect.top };
		const x = mouse.x - M.left;
		const y = mouse.y - M.top;
		let best: Hit | null = null;
		let bestD = PICK_R2;
		const scan = (dots: Pixel[], k: Hit['kind']) => {
			for (let i = 0; i < dots.length; i++) {
				const d = (x - dots[i].px) ** 2 + (y - dots[i].py) ** 2;
				if (d < bestD) {
					bestD = d;
					best = { kind: k, index: i };
				}
			}
		};
		scan(solar, 'solar');
		if (best === null) {
			scan(minimum, 'minimum');
			scan(measured, 'measured');
		}
		hit = best;
	}

	const scrub = createScrub({ onScrub: hitAt, onEnd: () => (hit = null) });

	let tipPoint = $derived.by<PlotPoint | null>(() => {
		if (!hit) return null;
		if (hit.kind === 'solar') return points.solar[hit.index] ?? null;
		return (hit.kind === 'minimum' ? points.minimum : points.measured)[hit.index] ?? null;
	});
	let tipName = $derived(hit?.kind === 'solar' ? solar[hit.index]?.name : undefined);

	function vsEarth(ratio: number): string {
		return m.earth_times({ value: ltrIsolate(sigFigures(ratio)) });
	}

	/** The rows of the tooltip, label and value, in axis order. */
	let tipRows = $derived.by<[string, string][]>(() => {
		if (!tipPoint || !hit) return [];
		const massLabel = hit.kind === 'minimum' ? m.planet_plot_legend_minimum() : m.exoplanet_mass();
		if (kind === 'radius') {
			return [
				[massLabel, vsEarth(tipPoint.x)],
				[ucfirst(m.property_name_radius()), vsEarth(tipPoint.y)]
			];
		}
		return [
			[
				m.semi_major_axis(),
				joinParts({ value: sigFigures(tipPoint.x), unit: formatUnit('astronomical_unit', true) })
			],
			[massLabel, vsEarth(tipPoint.y)]
		];
	});
</script>

<div
	class="relative w-full touch-pan-y"
	bind:this={containerEl}
	bind:clientWidth={width}
	style:height="{height}px"
	onmousemove={(e) => hitAt(e.clientX, e.clientY)}
	onmouseleave={() => (hit = null)}
	{...scrub}
	data-vaul-no-drag
	role="group"
	aria-label={ariaLabel}
>
	{#if width > 0}
		<svg {width} {height} viewBox="0 0 {width} {height}" class="block">
			<g transform="translate({M.left},{M.top})">
				<rect width={innerW} height={innerH} class="fill-muted/10" />
				<g class="pointer-events-none">
					<path
						d={measuredPath}
						stroke={PLANET_PLOT_COLORS.measured}
						stroke-width={DOT}
						stroke-linecap="round"
						stroke-opacity="0.55"
						fill="none"
					/>
					<path
						d={minimumPath}
						stroke={PLANET_PLOT_COLORS.minimum}
						stroke-width="0.9"
						stroke-opacity="0.7"
						fill="none"
					/>
				</g>
				<rect width={innerW} height={innerH} fill="none" class="stroke-border" stroke-width="1" />
				{#each solar as s, i (s.id)}
					{@const label = labels[i]}
					<a
						href={focusHref(appState, s.id, s.name)}
						onclick={focusClick(focusObject, s.id, s.name)}
						aria-label={s.name}
					>
						<circle
							cx={s.px}
							cy={s.py}
							r={SOLAR}
							class="fill-foreground stroke-background"
							stroke-width="1.5"
						/>
						{#if label}
							<text
								x={label.x}
								y={label.y}
								text-anchor={rtl ? MIRRORED[label.anchor] : label.anchor}
								dominant-baseline="central"
								class="planet-label"
							>
								{s.name}
							</text>
						{/if}
					</a>
				{/each}
				<ScatterAxes
					{innerW}
					{innerH}
					marginLeft={M.left}
					marginBottom={M.bottom}
					{xScale}
					{yScale}
					{xTicks}
					{yTicks}
					{formatTick}
					xLabel={kind === 'radius' ? m.planet_plot_axis_mass() : m.scatter_axis_a()}
					yLabel={kind === 'radius' ? m.planet_plot_axis_radius() : m.planet_plot_axis_mass()}
				/>
				{#if hit && tipPoint}
					{@const p = toPixel(tipPoint)}
					<circle
						cx={p.px}
						cy={p.py}
						r={hit.kind === 'solar' ? SOLAR + 2 : DOT + 1}
						fill="none"
						class="stroke-foreground pointer-events-none"
						stroke-width="1"
					/>
				{/if}
			</g>
		</svg>
	{/if}

	{#if tipRows.length}
		<div
			class="bg-foreground text-background pointer-events-none absolute z-50 -translate-y-full rounded-md px-2 py-1 text-xs shadow-md"
			style:left="{scatterTooltipLeft(mouse.x, width)}px"
			style:top="{mouse.y - 10}px"
			style:max-width="{SCATTER_TOOLTIP_MAX_W}px"
		>
			{#if tipName}
				<div class="font-semibold">{tipName}</div>
			{/if}
			{#each tipRows as [label, value] (label)}
				<div class="tabular-nums">
					<span class="text-background/70">{label}</span>
					{value}
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.planet-label {
		font-size: 10px;
		font-weight: 500;
		fill: var(--color-foreground);
		paint-order: stroke;
		stroke: var(--color-background);
		stroke-width: 3px;
		stroke-linejoin: round;
	}
</style>
