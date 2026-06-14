<script lang="ts">
	import ChevronLeftIcon from '@lucide/svelte/icons/chevron-left';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import * as m from '$lib/paraglide/messages.js';
	import { compact } from '$lib/search/format';
	import type { SearchModel } from '$lib/search/model.svelte';

	let { model }: { model: SearchModel } = $props();

	const total = $derived(model.result.estimatedTotalHits);
	const lo = $derived((model.page - 1) * model.pageSize + 1);
	const hi = $derived(Math.min(total, model.page * model.pageSize));
</script>

{#if model.pageCount > 1}
	<div class="flex items-center justify-between gap-2.5 px-1 pt-2.5 pb-0.5">
		<span class="text-[11px] tabular-nums text-muted-foreground">
			{m.search_page_range({
				lo: lo.toLocaleString(),
				hi: hi.toLocaleString(),
				total: compact(total)
			})}
		</span>
		<div class="flex gap-1.5">
			<button
				type="button"
				class="grid h-7 w-[30px] place-items-center rounded-md border border-border text-foreground transition-colors hover:bg-accent disabled:opacity-40"
				disabled={model.page <= 1}
				aria-label={m.search_prev_page()}
				onclick={() => model.setPage(model.page - 1)}
			>
				<ChevronLeftIcon class="size-3.5" />
			</button>
			<span class="grid min-w-[30px] place-items-center text-xs tabular-nums text-foreground">
				{model.page} / {compact(model.pageCount)}
			</span>
			<button
				type="button"
				class="grid h-7 w-[30px] place-items-center rounded-md border border-border text-foreground transition-colors hover:bg-accent disabled:opacity-40"
				disabled={model.page >= model.pageCount}
				aria-label={m.search_next_page()}
				onclick={() => model.setPage(model.page + 1)}
			>
				<ChevronRightIcon class="size-3.5" />
			</button>
		</div>
	</div>
{/if}
