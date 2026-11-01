<script lang="ts">
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import CheckIcon from '@lucide/svelte/icons/check';
	import { untrack, tick, onMount } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import { capitalize } from '$lib/search/format';
	import { formatCompactNumber } from '$lib/format/quantities';
	import type { SearchModel } from '$lib/search/model.svelte';
	import type { FilterNode, FilterLeaf } from '$lib/search/tree';
	import { rangeDef } from '$lib/search/ranges';
	import { hasBound } from '$lib/search/client';
	import BackPill from './BackPill.svelte';
	import RangeControl from './RangeControl.svelte';

	let {
		model,
		root,
		openTo,
		onClose
	}: { model: SearchModel; root: FilterNode; openTo?: string; onClose?: () => void } = $props();

	const messages = m as unknown as Record<string, (() => string) | undefined>;

	// Navigation stack: empty = root level, else the drilled-into path. Opening
	// the popover to edit a specific chip (`openTo`) starts on that child node.
	const opened = untrack(() => (openTo ? root.children?.find((c) => c.id === openTo) : undefined));
	let path = $state<FilterNode[]>(opened ? [opened] : []);
	const current = $derived(path.length ? path[path.length - 1] : root);
	const atRoot = $derived(path.length === 0);
	const shown = $derived(current.children ?? []);
	const leaves = $derived(current.leaves ?? []);
	const sections = $derived((current.sections ?? []).filter((s) => s.leaves.length > 0));
	const ranges = $derived(current.ranges ?? []);
	// Apart from the {#if} below: Svelte drops the parens of `(A || B) && C`.
	const hasControls = $derived(leaves.length > 0 || ranges.length > 0);

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
	// By value: a family with two parents shows under both, and counts once.
	function activeUnder(node: FilterNode, seen = new Set<string>()): number {
		const own = [...(node.leaves ?? []), ...(node.sections ?? []).flatMap((s) => s.leaves)];
		for (const leaf of own.filter(leafChecked)) {
			seen.add(leaf.kind === 'bool' ? leaf.facet : `${leaf.facet}:${leaf.values}`);
		}
		for (const f of node.ranges ?? []) if (hasBound(model.rangeOf(f))) seen.add(f);
		for (const child of node.children ?? []) activeUnder(child, seen);
		return seen.size;
	}

	let dialogEl = $state<HTMLDivElement | null>(null);
	let listEl = $state<HTMLDivElement | null>(null);

	// Focus the dialog itself on open so its Escape handler is live immediately
	// (before any tab in) and SRs announce the dialog.
	onMount(() => dialogEl?.focus());

	// Drilling swaps the whole list, unmounting the focused button (which would
	// otherwise drop focus to <body>); move focus onto the new level's first
	// control instead.
	function navigate(next: FilterNode[]) {
		path = next;
		tick().then(() => listEl?.querySelector<HTMLElement>('button, input')?.focus());
	}

	function onKeyDown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.stopPropagation();
			onClose?.();
		}
	}
</script>

{#snippet leafRow(leaf: FilterLeaf)}
	{@const checked = leafChecked(leaf)}
	<button
		type="button"
		role="checkbox"
		aria-checked={checked}
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
		<span class="min-w-0 flex-1 truncate text-sm text-foreground">{capitalize(leaf.label)}</span>
		{#if leaf.count != null}
			<span class="shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground"
				>{formatCompactNumber(leaf.count)}</span
			>
		{/if}
	</button>
{/snippet}

<div
	bind:this={dialogEl}
	class="absolute end-0 top-9 z-40 flex max-h-[440px] w-[288px] flex-col overflow-hidden rounded-xl border border-border bg-popover shadow-2xl"
	role="dialog"
	tabindex="-1"
	aria-label={m.search_filter()}
	onkeydown={onKeyDown}
>
	<div class="flex items-center gap-1.5 border-b border-border px-2 py-2">
		{#if !atRoot}
			<BackPill label={capitalize(current.label)} onclick={() => navigate(path.slice(0, -1))} />
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

	<div class="no-scrollbar overflow-y-auto p-1.5" bind:this={listEl}>
		{#each leaves as leaf (leaf.id)}
			{@render leafRow(leaf)}
		{/each}

		{#each ranges as facet, i (facet)}
			{@const def = rangeDef(facet)}
			{#if i > 0 || leaves.length > 0}
				<div class="my-1 border-t border-border"></div>
			{/if}
			<RangeControl
				{def}
				label={capitalize(messages[def.labelKey]?.() ?? facet)}
				value={model.rangeOf(facet)}
				onchange={(b) => model.setRange(facet, b)}
			/>
		{/each}

		{#if hasControls && shown.length > 0}
			<div class="my-1 border-t border-border"></div>
		{/if}

		{#each shown as node (node.id)}
			{@const au = activeUnder(node)}
			<button
				type="button"
				class="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-start transition-colors hover:bg-accent"
				onclick={() => navigate([...path, node])}
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
						>{formatCompactNumber(node.count)}</span
					>
				{/if}
				<ChevronRightIcon class="size-4 text-muted-foreground rtl:rotate-180" />
			</button>
		{/each}

		{#each sections as section (section.id)}
			<div role="group" aria-label={section.label}>
				{#if section.label}
					<p class="px-2 pb-1 pt-2.5 text-xs font-medium text-muted-foreground">{section.label}</p>
				{:else if shown.length > 0}
					<div class="my-1 border-t border-border"></div>
				{/if}
				{#each section.leaves as leaf (leaf.id)}
					{@render leafRow(leaf)}
				{/each}
			</div>
		{/each}
	</div>
</div>
