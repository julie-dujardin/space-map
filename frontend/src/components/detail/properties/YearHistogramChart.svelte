<script lang="ts">
	import { LayerCake, Svg, Html } from 'layercake';
	import { scaleBand } from 'd3-scale';
	import * as m from '$lib/paraglide/messages.js';
	import { formatNumber } from '$lib/format/quantities';
	import Bars from '$lib/charts/Bars.svelte';
	import AxisX from '$lib/charts/AxisX.svelte';
	import BarHover from '$lib/charts/BarHover.svelte';
	import HoverTooltip from '$lib/charts/HoverTooltip.svelte';
	import OverlayLine from '$lib/charts/OverlayLine.svelte';

	type Kind = 'launch' | 'discovery';
	interface Props {
		histogram: Record<string, number>;
		kind: Kind;
		height?: number;
	}
	let { histogram, kind, height = 110 }: Props = $props();

	function tooltipCount(n: number): string {
		return kind === 'discovery'
			? m.tooltip_discoveries_count({ count: n })
			: m.tooltip_launches_count({ count: n });
	}

	const PADDING = { top: 18, right: 4, bottom: 16, left: 4 };

	// Cap bar count so each bar stays visually distinct; long spans bin into
	// 5/10/25-year buckets via NICE_STEPS. Centuries-wide spans (ancient
	// comet observations) get century bins, keeping the chart readable
	// without dropping historical datapoints.
	const BAR_TARGET = 40;
	const NICE_STEPS = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000];

	let series = $derived.by(() => {
		const years = Object.keys(histogram)
			.map((y) => parseInt(y, 10))
			.filter((y) => Number.isFinite(y))
			.sort((a, b) => a - b);
		if (years.length === 0) return [];

		const start = years[0];
		const end = years[years.length - 1];
		const span = end - start + 1;
		const target = Math.ceil(span / BAR_TARGET);
		const binSize = NICE_STEPS.find((s) => s >= target) ?? 100;
		// Snap bin starts to multiples of binSize so labels read 1900/1910/…
		const binStartFloor = Math.floor(start / binSize) * binSize;

		let running = 0;
		const out: {
			year: number;
			yearEnd: number;
			count: number;
			cumulative: number;
			binSize: number;
		}[] = [];
		for (let binStart = binStartFloor; binStart <= end; binStart += binSize) {
			const binEnd = binStart + binSize - 1;
			let count = 0;
			for (let y = binStart; y <= binEnd; y++) {
				count += histogram[String(y)] ?? 0;
			}
			running += count;
			out.push({
				year: binStart,
				yearEnd: Math.min(binEnd, end),
				count,
				cumulative: running,
				binSize
			});
		}
		return out;
	});

	let hoveredIndex = $state<number | null>(null);
	let binSize = $derived(series[0]?.binSize ?? 1);

	// AxisX filters by `year % every === 0`; `every` is therefore a year
	// interval, not a bar count. Target ~6 visible labels across the span.
	let tickEvery = $derived.by(() => {
		if (series.length === 0) return 1;
		const span = series[series.length - 1].year - series[0].year + binSize;
		const target = Math.ceil(span / 6);
		return NICE_STEPS.find((s) => s >= target && s >= binSize) ?? 100;
	});

	function formatYear(y: unknown): string {
		return String(Number(y));
	}

	function formatBinRange(d: { year: number; yearEnd: number }): string {
		return d.year === d.yearEnd ? String(d.year) : `${d.year}–${d.yearEnd}`;
	}
</script>

{#if series.length > 0}
	<div class="flex flex-col gap-1">
		<div class="text-muted-foreground flex justify-end gap-2 text-[10px]">
			<span class="flex items-center gap-1">
				<span class="bg-foreground inline-block size-2 rounded-[1px] opacity-70"></span>
				{binSize === 1 ? m.legend_per_year() : m.legend_per_n_years({ n: binSize })}
			</span>
			<span class="flex items-center gap-1">
				<span class="bg-sky-400 inline-block h-px w-2.5"></span>
				{m.legend_cumulative()}
			</span>
		</div>
		<div style:height="{height}px" role="img" onmouseleave={() => (hoveredIndex = null)}>
			<LayerCake
				padding={PADDING}
				x="year"
				y="count"
				xScale={scaleBand().paddingInner(0.15).paddingOuter(0)}
				xDomain={series.map((d) => d.year)}
				yDomain={[0, null]}
				data={series}
			>
				<Svg>
					<Bars />
					<OverlayLine yAccessor={(d) => Number(d.cumulative)} />
					<AxisX format={formatYear} every={tickEvery} />
					<BarHover onHover={(i) => (hoveredIndex = i)} />
				</Svg>
				<Html pointerEvents={false}>
					<HoverTooltip index={hoveredIndex}>
						{#snippet body(d)}
							<div class="font-semibold tabular-nums">
								{formatBinRange(d as { year: number; yearEnd: number })}
							</div>
							<div class="text-muted-foreground tabular-nums">
								{tooltipCount(d.count as number)}
							</div>
							<div class="text-muted-foreground tabular-nums">
								{formatNumber(d.cumulative as number)}
								{m.legend_cumulative()}
							</div>
						{/snippet}
					</HoverTooltip>
				</Html>
			</LayerCake>
		</div>
	</div>
{/if}
