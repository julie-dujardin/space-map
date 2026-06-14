<script lang="ts">
	import ArrowUpDownIcon from '@lucide/svelte/icons/arrow-up-down';
	import ArrowUpIcon from '@lucide/svelte/icons/arrow-up';
	import ArrowDownIcon from '@lucide/svelte/icons/arrow-down';
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import CheckIcon from '@lucide/svelte/icons/check';
	import * as m from '$lib/paraglide/messages.js';
	import { SORTS } from '$lib/search/model.svelte';
	import type { SearchModel } from '$lib/search/model.svelte';
	import type { SortId } from '$lib/search/client';

	let { model }: { model: SearchModel } = $props();

	let open = $state(false);

	const messages = m as unknown as Record<string, (() => string) | undefined>;
	function label(key: string): string {
		return messages[key]?.() ?? key;
	}
	const current = $derived(SORTS.find((s) => s.id === model.sort) ?? SORTS[0]);

	function choose(id: SortId) {
		model.setSort(id);
		open = false;
	}

	function onFocusOut(e: FocusEvent) {
		const next = e.relatedTarget as Node | null;
		if (next && (e.currentTarget as HTMLElement).contains(next)) return;
		open = false;
	}
</script>

<div class="relative inline-flex shrink-0 items-center" onfocusout={onFocusOut}>
	<button
		type="button"
		class="inline-flex h-[30px] items-center gap-1.5 rounded-s-lg border border-border px-2 text-xs whitespace-nowrap text-foreground transition-colors hover:bg-accent {open
			? 'bg-accent'
			: ''}"
		onclick={() => (open = !open)}
	>
		<ArrowUpDownIcon class="size-3.5" />
		<span class="text-muted-foreground">{m.search_sort()}</span>
		<span class="font-medium">{label(current.key)}</span>
		<ChevronDownIcon class="size-3" />
	</button>
	<button
		type="button"
		class="inline-flex h-[30px] w-[30px] items-center justify-center rounded-e-lg border border-s-0 border-border text-foreground transition-colors hover:bg-accent {model.reverse
			? 'bg-accent'
			: ''}"
		aria-label={m.search_sort_reverse()}
		title={m.search_sort_reverse()}
		onclick={() => model.toggleReverse()}
	>
		{#if model.reverse}<ArrowUpIcon class="size-3.5" />{:else}<ArrowDownIcon
				class="size-3.5"
			/>{/if}
	</button>

	{#if open}
		<div
			class="absolute end-0 top-9 z-30 min-w-[200px] rounded-xl border border-border bg-popover p-1.5 shadow-xl"
		>
			{#each SORTS as s (s.id)}
				<button
					type="button"
					class="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-start text-sm text-foreground transition-colors hover:bg-accent"
					onclick={() => choose(s.id)}
				>
					<span class="w-3.5 shrink-0">
						{#if s.id === model.sort}<CheckIcon class="size-3.5" />{/if}
					</span>
					{label(s.key)}
				</button>
			{/each}
		</div>
	{/if}
</div>
