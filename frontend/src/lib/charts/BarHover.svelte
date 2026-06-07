<script lang="ts">
	import { getContext } from 'svelte';
	import type { Readable } from 'svelte/store';

	interface BandScale {
		(d: unknown): number;
		bandwidth: () => number;
		step: () => number;
	}
	interface Ctx {
		data: Readable<Array<Record<string, unknown>>>;
		xGet: Readable<(d: Record<string, unknown>) => number>;
		xScale: Readable<BandScale>;
		height: Readable<number>;
	}

	interface Props {
		onHover: (index: number | null) => void;
	}
	let { onHover }: Props = $props();

	const { data, xGet, xScale, height } = getContext<Ctx>('LayerCake');
</script>

<g class="hover-areas">
	{#each $data as d, i (i)}
		{@const bw = $xScale.bandwidth()}
		{@const step = $xScale.step()}
		{@const x = $xGet(d) - (step - bw) / 2}
		<rect
			{x}
			y="0"
			width={step}
			height={$height}
			fill="transparent"
			role="presentation"
			onmouseenter={() => onHover(i)}
		></rect>
	{/each}
</g>
