<script lang="ts" generics="T extends { name: string; n: number }">
	/** Ranked bar list with a pager — launch-vehicle variants, reusable vehicles,
	 *  launch sites, constellations. The label cell is a snippet because each
	 *  list links its rows differently (group route, Wikipedia, or neither). */

	import { formatNumber } from '$lib/format/quantities';
	import ChartPager from './ChartPager.svelte';
	import type { Snippet } from 'svelte';

	interface Props {
		entries: T[];
		title: string;
		/** Small-caps hint for what `n` counts, e.g. "launches". */
		unit?: string;
		label: Snippet<[T]>;
		pageSize?: number;
	}
	let { entries, title, unit, label, pageSize = 8 }: Props = $props();

	// Bars scale against the whole set, not the page, so pages stay comparable.
	let maxCount = $derived(entries.length > 0 ? Math.max(...entries.map((e) => e.n)) : 0);
	let pageCount = $derived(Math.max(1, Math.ceil(entries.length / pageSize)));
	let page = $state(0);
	// A shorter list (another group focused) would otherwise strand the page.
	$effect(() => {
		if (page > pageCount - 1) page = pageCount - 1;
	});
	let visible = $derived(entries.slice(page * pageSize, page * pageSize + pageSize));
</script>

{#if entries.length > 0}
	<div class="flex flex-col gap-1">
		<div class="flex items-baseline justify-between gap-2">
			<h3 class="text-sm font-medium">{title}</h3>
			<div class="flex items-baseline gap-2">
				{#if unit}
					<span class="text-muted-foreground text-[10px] uppercase">{unit}</span>
				{/if}
				<ChartPager {page} {pageCount} onpage={(p) => (page = p)} />
			</div>
		</div>
		<div class="border-border/60 border-t"></div>
		<ul class="flex flex-col gap-2 pt-1 text-sm">
			{#each visible as e (e.name)}
				<li class="flex flex-col gap-1">
					<div class="flex items-baseline justify-between gap-2">
						{@render label(e)}
						<span class="text-muted-foreground tabular-nums">{formatNumber(e.n)}</span>
					</div>
					<div class="bg-muted h-1 overflow-hidden rounded-full">
						<div
							class="bg-primary h-full rounded-full"
							style:width="{maxCount > 0 ? (e.n / maxCount) * 100 : 0}%"
						></div>
					</div>
				</li>
			{/each}
		</ul>
	</div>
{/if}
