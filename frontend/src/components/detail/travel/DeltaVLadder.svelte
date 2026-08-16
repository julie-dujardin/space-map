<!--
  The Δv ladder: a stacked bar of a route's burns, widths proportional to Δv.
  Coasts carry no Δv so never appear — this is a budget, not a timeline.
  Segments get a gap and their own labelled figure below, so identity never
  rests on colour alone.
-->
<script lang="ts">
	import type { RouteLeg } from '$lib/math/travel';
	import { formatDv } from '$lib/travel/format';
	import { legLabel } from './leg-labels';

	interface Props {
		legs: RouteLeg[];
		/** Drop the legend where the caller already lists the steps. */
		showLegend?: boolean;
	}
	let { legs, showLegend = true }: Props = $props();

	let burns = $derived(legs.filter((leg) => leg.dvKms > 0));
	let total = $derived(burns.reduce((sum, leg) => sum + leg.dvKms, 0));
</script>

<div class="travel-ladder flex flex-col gap-2">
	<div class="flex h-2.5 w-full gap-0.5 overflow-hidden">
		{#each burns as leg (leg.kind)}
			<div
				class="h-full first:rounded-s-sm last:rounded-e-sm"
				style="width: {total > 0
					? (leg.dvKms / total) * 100
					: 0}%; background: var(--leg-{leg.kind})"
			></div>
		{/each}
	</div>

	{#if showLegend}
		<dl class="grid grid-cols-[auto_1fr_auto] items-baseline gap-x-2 gap-y-1 text-xs">
			{#each burns as leg (leg.kind)}
				<span
					class="size-2 shrink-0 self-center rounded-[2px]"
					style="background: var(--leg-{leg.kind})"
				></span>
				<dt class="text-muted-foreground min-w-0 truncate">{legLabel(leg.kind)}</dt>
				<dd class="tabular-nums">{formatDv(leg.dvKms)}</dd>
			{/each}
		</dl>
	{/if}
</div>

<style>
	/* Categorical slots validated for CVD separation against both surfaces.
	   Departure and arrival burns must stay tellable apart where they touch. */
	.travel-ladder {
		--leg-ascent: #2a78d6;
		--leg-injection: #eb6834;
		--leg-capture: #1baf7a;
		--leg-descent: #eda100;
		--leg-cruise: transparent;
		/* One drive, one hue: boost/brake are the same burn flipped, told apart by
		   lightness, which survives colour blindness. */
		--leg-boost: #5a3fb8;
		--leg-brake: #a893e8;
		/* Same scheme for a spiral: one drive through all three stretches —
		   crossing plus a climb out of each well. */
		--leg-powered-cruise: #6f4fd0;
		--leg-spiral-out: #4a3a91;
		--leg-spiral-in: #a893e8;
	}
	:global(.dark) .travel-ladder {
		--leg-ascent: #3987e5;
		--leg-injection: #d95926;
		--leg-capture: #199e70;
		--leg-descent: #c98500;
		--leg-boost: #7d63d9;
		--leg-brake: #bbaaee;
		--leg-powered-cruise: #8f78e0;
		--leg-spiral-out: #6350b5;
		--leg-spiral-in: #bbaaee;
	}
</style>
