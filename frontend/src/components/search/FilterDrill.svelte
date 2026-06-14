<script lang="ts">
	import ChevronLeftIcon from '@lucide/svelte/icons/chevron-left';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import CheckIcon from '@lucide/svelte/icons/check';
	import * as m from '$lib/paraglide/messages.js';
	import { compact } from '$lib/search/format';
	import type { SearchModel } from '$lib/search/model.svelte';
	import type { FilterCategory, FilterLeaf } from '$lib/search/tree';

	let { model, categories }: { model: SearchModel; categories: FilterCategory[] } = $props();

	let drilled = $state<string | null>(null);
	const current = $derived(categories.find((c) => c.id === drilled) ?? null);

	function leafChecked(leaf: FilterLeaf): boolean {
		return leaf.kind === 'bool'
			? !!model.filters[leaf.facet]
			: model.isChecked(leaf.facet, leaf.values);
	}
	function toggleLeaf(leaf: FilterLeaf) {
		if (leaf.kind === 'bool') model.toggleBool(leaf.facet);
		else model.toggleValues(leaf.facet, leaf.values);
	}
	function activeUnder(cat: FilterCategory): number {
		return cat.leaves.filter(leafChecked).length;
	}
</script>

<div
	class="absolute end-0 top-9 z-40 flex max-h-[440px] w-[288px] flex-col overflow-hidden rounded-xl border border-border bg-popover shadow-2xl"
>
	<!-- header -->
	<div class="flex items-center gap-1.5 border-b border-border px-2 py-2">
		{#if current}
			<button
				type="button"
				class="inline-flex h-[26px] items-center gap-1 rounded-lg bg-accent px-2 text-sm font-medium text-foreground"
				onclick={() => (drilled = null)}
			>
				<ChevronLeftIcon class="size-4" />
				<span class="whitespace-nowrap">{current.label}</span>
			</button>
		{:else}
			<span class="ps-1 text-sm font-semibold text-foreground">{m.search_add_filter()}</span>
		{/if}
		<span class="flex-1"></span>
		{#if model.activeCount > 0}
			<button
				type="button"
				class="px-1 text-xs text-primary hover:underline"
				onclick={() => model.clearFilters()}>{m.search_clear_all()}</button
			>
		{/if}
	</div>

	<div class="no-scrollbar overflow-y-auto p-1.5">
		{#if current}
			{#each current.leaves as leaf (leaf.id)}
				{@const checked = leafChecked(leaf)}
				<button
					type="button"
					class="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-start transition-colors hover:bg-accent"
					onclick={() => toggleLeaf(leaf)}
				>
					<span
						class="grid size-4 shrink-0 place-items-center rounded border {checked
							? 'border-foreground bg-foreground text-background'
							: 'border-muted-foreground'}"
					>
						{#if checked}<CheckIcon class="size-3" />{/if}
					</span>
					<span class="min-w-0 flex-1 truncate text-sm text-foreground">{leaf.label}</span>
					{#if leaf.count != null}
						<span class="shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground"
							>{compact(leaf.count)}</span
						>
					{/if}
				</button>
			{/each}
		{:else}
			{#each categories as cat (cat.id)}
				{@const au = activeUnder(cat)}
				<button
					type="button"
					class="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-start transition-colors hover:bg-accent"
					onclick={() => (drilled = cat.id)}
				>
					<span class="min-w-0 flex-1 truncate text-sm text-foreground">{cat.label}</span>
					{#if au > 0}
						<span
							class="grid h-4 min-w-4 place-items-center rounded-full bg-primary/20 px-1.5 text-[10px] tabular-nums text-primary"
							>{au}</span
						>
					{/if}
					<ChevronRightIcon class="size-4 text-muted-foreground" />
				</button>
			{/each}
		{/if}
	</div>
</div>
