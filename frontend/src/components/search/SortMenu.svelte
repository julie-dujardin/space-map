<script lang="ts">
	import ArrowUpDownIcon from '@lucide/svelte/icons/arrow-up-down';
	import ArrowUpIcon from '@lucide/svelte/icons/arrow-up';
	import ArrowDownIcon from '@lucide/svelte/icons/arrow-down';
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import * as m from '$lib/paraglide/messages.js';
	import * as DropdownMenu from '$lib/components/ui/dropdown-menu/index.js';
	import { SORTS } from '$lib/search/model.svelte';
	import type { SearchModel } from '$lib/search/model.svelte';
	import type { SortId } from '$lib/search/client';

	let { model }: { model: SearchModel } = $props();

	const messages = m as unknown as Record<string, (() => string) | undefined>;
	function label(key: string): string {
		return messages[key]?.() ?? key;
	}
	const current = $derived(SORTS.find((s) => s.id === model.sort) ?? SORTS[0]);
</script>

<div class="relative inline-flex shrink-0 items-center">
	<DropdownMenu.Root>
		<DropdownMenu.Trigger
			class="inline-flex h-[30px] cursor-pointer items-center gap-1.5 rounded-s-lg border border-border px-2 text-xs whitespace-nowrap text-foreground transition-colors hover:bg-accent data-[state=open]:bg-accent"
		>
			<ArrowUpDownIcon class="size-3.5" />
			<span class="text-muted-foreground">{m.search_sort()}</span>
			<span class="font-medium">{label(current.key)}</span>
			<ChevronDownIcon class="size-3" />
		</DropdownMenu.Trigger>
		<!-- Unportalled: the search panel is its own stacking layer (z-55 on the
		     map, z-70 in the site sheet), and a menu on <body> would sit under it. -->
		<DropdownMenu.Content align="end" class="w-auto min-w-[200px]" portalProps={{ disabled: true }}>
			<DropdownMenu.RadioGroup
				value={model.sort}
				onValueChange={(id) => model.setSort(id as SortId)}
			>
				{#each SORTS as s (s.id)}
					<DropdownMenu.RadioItem value={s.id} class="cursor-pointer">
						{label(s.key)}
					</DropdownMenu.RadioItem>
				{/each}
			</DropdownMenu.RadioGroup>
		</DropdownMenu.Content>
	</DropdownMenu.Root>
	<button
		type="button"
		class="inline-flex h-[30px] w-[30px] items-center justify-center rounded-e-lg border border-s-0 border-border text-foreground transition-colors hover:bg-accent {model.reverse
			? 'bg-accent'
			: ''}"
		aria-label={m.search_sort_reverse()}
		aria-pressed={model.reverse}
		title={m.search_sort_reverse()}
		onclick={() => model.toggleReverse()}
	>
		{#if model.reverse}<ArrowUpIcon class="size-3.5" />{:else}<ArrowDownIcon
				class="size-3.5"
			/>{/if}
	</button>
</div>
