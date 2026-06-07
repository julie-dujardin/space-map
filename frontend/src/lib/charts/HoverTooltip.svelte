<script lang="ts">
	import { getContext, type Snippet } from 'svelte';
	import type { Readable } from 'svelte/store';

	interface BandScale {
		(d: unknown): number;
		bandwidth: () => number;
	}
	interface Ctx {
		data: Readable<Array<Record<string, unknown>>>;
		xGet: Readable<(d: Record<string, unknown>) => number>;
		xScale: Readable<BandScale>;
		width: Readable<number>;
	}

	interface Props {
		index: number | null;
		body: Snippet<[Record<string, unknown>]>;
	}
	let { index, body }: Props = $props();

	const { data, xGet, xScale, width } = getContext<Ctx>('LayerCake');

	let tooltipWidth = $state(0);

	let datum = $derived(index == null ? null : ($data[index] ?? null));

	let rawLeft = $derived(datum == null ? 0 : $xGet(datum) + $xScale.bandwidth() / 2);
	let halfW = $derived(tooltipWidth / 2);
	let clampedLeft = $derived(
		tooltipWidth === 0 ? rawLeft : Math.min(Math.max(halfW, rawLeft), $width - halfW)
	);
</script>

{#if datum}
	<div
		bind:clientWidth={tooltipWidth}
		class="bg-popover text-popover-foreground border-border pointer-events-none absolute z-50 rounded-md border px-2 py-1 text-xs whitespace-nowrap shadow-md"
		style:left="{clampedLeft}px"
		style:top="-4px"
		style:transform="translate(-50%, -100%)"
		style:visibility={tooltipWidth === 0 ? 'hidden' : 'visible'}
	>
		{@render body(datum)}
	</div>
{/if}
