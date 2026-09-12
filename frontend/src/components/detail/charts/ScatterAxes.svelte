<script lang="ts">
	/** Bottom and left axes of a zone scatter: tick marks, tick labels and one
	 *  rotated axis title each. */
	interface Props {
		innerW: number;
		innerH: number;
		/** Chart margins; the axis titles sit in them. */
		marginLeft: number;
		marginBottom: number;
		xScale: (v: number) => number;
		yScale: (v: number) => number;
		xTicks: number[];
		yTicks: number[];
		formatTick: (v: number) => string;
		xLabel: string;
		yLabel: string;
	}
	let {
		innerW,
		innerH,
		marginLeft,
		marginBottom,
		xScale,
		yScale,
		xTicks,
		yTicks,
		formatTick,
		xLabel,
		yLabel
	}: Props = $props();
</script>

<g transform="translate(0,{innerH})">
	<line x2={innerW} class="stroke-muted-foreground/60" />
	{#each xTicks as t (t)}
		{@const tx = xScale(t)}
		<g transform="translate({tx},0)">
			<line y2={3} class="stroke-muted-foreground/60" />
			<text y={12} text-anchor="middle" class="fill-muted-foreground" style:font-size="9px">
				{formatTick(t)}
			</text>
		</g>
	{/each}
	<text
		x={innerW / 2}
		y={marginBottom - 4}
		text-anchor="middle"
		class="fill-muted-foreground"
		style:font-size="9px"
	>
		{xLabel}
	</text>
</g>
<g>
	<line y2={innerH} class="stroke-muted-foreground/60" />
	{#each yTicks as t (t)}
		{@const ty = yScale(t)}
		<g transform="translate(0,{ty})">
			<line x2={-3} class="stroke-muted-foreground/60" />
			<text x={-5} dy={3} text-anchor="end" class="fill-muted-foreground" style:font-size="9px">
				{formatTick(t)}
			</text>
		</g>
	{/each}
	<text
		transform="translate({-marginLeft + 10},{innerH / 2}) rotate(-90)"
		text-anchor="middle"
		class="fill-muted-foreground"
		style:font-size="9px"
	>
		{yLabel}
	</text>
</g>
