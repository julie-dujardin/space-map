<script lang="ts">
	import { getContext } from 'svelte';
	import type { Readable } from 'svelte/store';

	interface BandScale {
		(d: unknown): number;
		bandwidth: () => number;
	}
	interface Ctx {
		data: Readable<Array<Record<string, unknown>>>;
		xGet: Readable<(d: Record<string, unknown>) => number>;
		yGet: Readable<(d: Record<string, unknown>) => number>;
		xScale: Readable<BandScale>;
		height: Readable<number>;
	}

	interface Props {
		/** Optional zero-based index to highlight with the accent color. */
		accentIndex?: number;
		minBarHeightPx?: number;
	}
	let { accentIndex, minBarHeightPx = 2 }: Props = $props();

	const { data, xGet, yGet, xScale, height } = getContext<Ctx>('LayerCake');
</script>

<g class="bars">
	{#each $data as d, i (i)}
		{@const x = $xGet(d)}
		{@const y = $yGet(d)}
		{@const w = $xScale.bandwidth()}
		{@const rawH = $height - y}
		{@const h = rawH > 0 ? Math.max(rawH, minBarHeightPx) : 0}
		<rect
			{x}
			y={$height - h}
			width={w}
			height={h}
			rx="1.5"
			class={i === accentIndex ? 'accent' : 'bar'}
		/>
	{/each}
</g>

<style>
	.bar {
		fill: var(--color-primary);
		opacity: 0.55;
	}
	.accent {
		fill: var(--color-primary);
		opacity: 1;
	}
</style>
