<script lang="ts">
	import ChevronLeftIcon from '@lucide/svelte/icons/chevron-left';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import CheckIcon from '@lucide/svelte/icons/check';
	import { untrack } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import { capitalize, compact } from '$lib/search/format';
	import type { SearchModel } from '$lib/search/model.svelte';
	import type { FilterNode, FilterLeaf } from '$lib/search/tree';
	import { rangeDef } from '$lib/search/ranges';
	import { hasBound } from '$lib/search/client';
	import RangeControl from './RangeControl.svelte';

	let { model, root, openTo }: { model: SearchModel; root: FilterNode; openTo?: string } = $props();

	const messages = m as unknown as Record<string, (() => string) | undefined>;

	// Navigation stack: empty = root level; else the drilled-into path. When the
	// popover is opened to edit a specific chip (`openTo`), start on that child
	// node; resolved once at mount, matching how drilling pushes node objects.
	const opened = untrack(() => (openTo ? root.children?.find((c) => c.id === openTo) : undefined));
	let path = $state<FilterNode[]>(opened ? [opened] : []);
	const current = $derived(path.length ? path[path.length - 1] : root);
	const atRoot = $derived(path.length === 0);
	const shown = $derived(current.children ?? []);
	const leaves = $derived(current.leaves ?? []);
	const ranges = $derived(current.ranges ?? []);

	function leafChecked(leaf: FilterLeaf): boolean {
		return leaf.kind === 'bool'
			? !!model.filters[leaf.facet]
			: model.isChecked(leaf.facet, leaf.values);
	}
	function toggleLeaf(leaf: FilterLeaf) {
		if (leaf.kind === 'bool') model.toggleBool(leaf.facet);
		else model.toggleValues(leaf.facet, leaf.values);
	}
	// Active selections anywhere under a node (its leaves + ranges + descendants).
	function activeUnder(node: FilterNode): number {
		let n = (node.leaves ?? []).filter(leafChecked).length;
		for (const f of node.ranges ?? []) if (hasBound(model.rangeOf(f))) n++;
		for (const child of node.children ?? []) n += activeUnder(child);
		return n;
	}
</script>

<div
	class="absolute end-0 top-9 z-40 flex max-h-[440px] w-[288px] flex-col overflow-hidden rounded-xl border border-border bg-popover shadow-2xl"
>
	<!-- header: back to parent, or the "Add filter" title at root -->
	<div class="flex items-center gap-1.5 border-b border-border px-2 py-2">
		{#if !atRoot}
			<button
				type="button"
				class="inline-flex h-[26px] items-center gap-1 rounded-lg bg-accent px-2 text-sm font-medium text-foreground"
				onclick={() => (path = path.slice(0, -1))}
			>
				<ChevronLeftIcon class="size-4" />
				<span class="whitespace-nowrap">{capitalize(current.label)}</span>
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
		<!-- direct toggle leaves at this level (All / NEO / PHA / Probes …) -->
		{#each leaves as leaf (leaf.id)}
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
				<span class="min-w-0 flex-1 truncate text-sm text-foreground">{capitalize(leaf.label)}</span
				>
				{#if leaf.count != null}
					<span class="shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground"
						>{compact(leaf.count)}</span
					>
				{/if}
			</button>
		{/each}

		<!-- numeric range sliders (Size / Brightness / Date) -->
		{#each ranges as facet, i (facet)}
			{@const def = rangeDef(facet)}
			{#if i > 0 || leaves.length > 0}
				<div class="my-1 border-t border-border"></div>
			{/if}
			<RangeControl
				{def}
				label={messages[def.labelKey]?.() ?? facet}
				value={model.rangeOf(facet)}
				onchange={(b) => model.setRange(facet, b)}
			/>
		{/each}

		<!-- a divider between this level's leaves and its drillable sub-groups -->
		{#if (leaves.length > 0 || ranges.length > 0) && shown.length > 0}
			<div class="my-1 border-t border-border"></div>
		{/if}

		<!-- drillable child nodes (type list at root; sub-categories within a type) -->
		{#each shown as node (node.id)}
			{@const au = activeUnder(node)}
			<button
				type="button"
				class="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-start transition-colors hover:bg-accent"
				onclick={() => (path = [...path, node])}
			>
				<span class="min-w-0 flex-1 truncate text-sm text-foreground">{capitalize(node.label)}</span
				>
				{#if au > 0}
					<span
						class="grid h-4 min-w-4 place-items-center rounded-full bg-primary/20 px-1.5 text-[10px] tabular-nums text-primary"
						>{au}</span
					>
				{:else if node.count != null}
					<span class="shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground"
						>{compact(node.count)}</span
					>
				{/if}
				<ChevronRightIcon class="size-4 text-muted-foreground" />
			</button>
		{/each}
	</div>
</div>
