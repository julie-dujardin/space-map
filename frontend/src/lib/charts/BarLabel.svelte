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
	}

	interface Props {
		index: number;
		text: string;
	}
	let { index, text }: Props = $props();

	const { data, xGet, yGet, xScale } = getContext<Ctx>('LayerCake');
	let point = $derived.by(() => {
		const d = $data[index];
		if (!d) return null;
		return { cx: $xGet(d) + $xScale.bandwidth() / 2, top: $yGet(d) };
	});
</script>

{#if point}
	<text class="label" x={point.cx} y={point.top - 4} text-anchor="middle">{text}</text>
{/if}

<style>
	.label {
		fill: var(--color-foreground);
		font-size: 10px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
</style>
