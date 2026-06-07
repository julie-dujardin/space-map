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

	interface Props {
		histogram: Record<string, number>;
		height?: number;
	}
	let { histogram, height = 110 }: Props = $props();

	const PADDING = { top: 18, right: 4, bottom: 16, left: 4 };

	let series = $derived.by(() => {
		const years = Object.keys(histogram)
			.map((y) => parseInt(y, 10))
			.filter((y) => Number.isFinite(y))
			.sort((a, b) => a - b);
		if (years.length === 0) return [];
		const start = years[0];
		const end = years[years.length - 1];
		let running = 0;
		const out: { year: number; count: number; cumulative: number }[] = [];
		for (let y = start; y <= end; y++) {
			const count = histogram[String(y)] ?? 0;
			running += count;
			out.push({ year: y, count, cumulative: running });
		}
		return out;
	});

	let peakIndex = $derived.by(() => {
		if (series.length === 0) return -1;
		let bestI = 0;
		for (let i = 1; i < series.length; i++) if (series[i].count > series[bestI].count) bestI = i;
		return bestI;
	});
	// Tick every other year once there are more than 8, so labels never overlap.
	let tickEvery = $derived(series.length > 8 ? 2 : 1);

	let hoveredIndex = $state<number | null>(null);

	function formatYear(y: unknown): string {
		const n = Number(y);
		const yy = (n % 100).toString().padStart(2, '0');
		return `'${yy}`;
	}
</script>

{#if series.length > 0}
	<div class="flex flex-col gap-1">
		<div class="text-muted-foreground flex justify-end gap-2 text-[10px]">
			<span class="flex items-center gap-1">
				<span class="bg-primary inline-block size-2 rounded-[1px] opacity-55"></span>
				{m.legend_per_year()}
			</span>
			<span class="flex items-center gap-1">
				<span class="bg-primary inline-block h-px w-2.5"></span>
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
					<Bars accentIndex={peakIndex} />
					<OverlayLine yAccessor={(d) => Number(d.cumulative)} />
					<AxisX format={formatYear} every={tickEvery} />
					<BarHover onHover={(i) => (hoveredIndex = i)} />
				</Svg>
				<Html pointerEvents={false}>
					<HoverTooltip index={hoveredIndex}>
						{#snippet body(d)}
							<div class="font-semibold tabular-nums">{d.year}</div>
							<div class="text-muted-foreground tabular-nums">
								{formatNumber(d.count as number)}
								{m.legend_per_year()}
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
