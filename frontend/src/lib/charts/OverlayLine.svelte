<script lang="ts">
	import { getContext } from 'svelte';
	import type { Readable } from 'svelte/store';

	interface BandScale {
		bandwidth: () => number;
	}
	interface Ctx {
		data: Readable<Array<Record<string, unknown>>>;
		xGet: Readable<(d: Record<string, unknown>) => number>;
		xScale: Readable<BandScale>;
		height: Readable<number>;
	}

	interface Props {
		/** Function returning the value plotted on the overlay's own y-scale. */
		yAccessor: (d: Record<string, unknown>) => number;
		/** Optional explicit max; defaults to the max of the accessor over the data. */
		yMax?: number;
	}
	let { yAccessor, yMax }: Props = $props();

	const { data, xGet, xScale, height } = getContext<Ctx>('LayerCake');

	let resolvedMax = $derived(yMax ?? Math.max(1, ...$data.map((d) => yAccessor(d))));

	let points = $derived(
		$data
			.map((d) => {
				const cx = $xGet(d) + $xScale.bandwidth() / 2;
				const cy = $height - (yAccessor(d) / resolvedMax) * $height;
				return `${cx.toFixed(2)},${cy.toFixed(2)}`;
			})
			.join(' ')
	);
</script>

{#if points}
	<polyline {points} class="overlay-line" />
{/if}

<style>
	.overlay-line {
		fill: none;
		stroke: var(--color-sky-400);
		stroke-width: 1.5;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
</style>
