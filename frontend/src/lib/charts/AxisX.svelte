<script lang="ts">
	import { getContext } from 'svelte';
	import type { Readable } from 'svelte/store';

	interface BandScale {
		(d: unknown): number;
		bandwidth: () => number;
		domain: () => unknown[];
	}
	interface Ctx {
		xScale: Readable<BandScale>;
		height: Readable<number>;
	}

	interface Props {
		format?: (d: unknown) => string;
		every?: number;
	}
	let { format = (d) => String(d), every = 1 }: Props = $props();

	const { xScale, height } = getContext<Ctx>('LayerCake');
	let ticks = $derived($xScale.domain().filter((_, i) => i % every === 0));
</script>

<g class="axis-x" transform="translate(0, {$height + 4})">
	{#each ticks as t (String(t))}
		<text
			x={$xScale(t) + $xScale.bandwidth() / 2}
			y="0"
			text-anchor="middle"
			dominant-baseline="hanging">{format(t)}</text
		>
	{/each}
</g>

<style>
	text {
		fill: var(--color-muted-foreground);
		font-size: 10px;
		font-variant-numeric: tabular-nums;
	}
</style>
