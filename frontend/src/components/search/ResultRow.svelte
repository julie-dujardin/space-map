<script lang="ts">
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import LayersIcon from '@lucide/svelte/icons/layers';
	import type { SearchHit } from '$lib/search/client';

	type Props = {
		hit: SearchHit;
		name: string;
		secondary: string;
		thumbnail?: string;
		/** DOM id referenced by the combobox input's aria-activedescendant. */
		id: string;
		active: boolean;
		onselect: () => void;
		onhover: () => void;
		/** Right-aligned value tied to the active sort (size/brightness/…). */
		metric?: { value: string; unit?: string };
	};

	let { hit, name, secondary, thumbnail, id, active, onselect, onhover, metric }: Props = $props();

	// Collection pages (constellations, organizations, orbit classes, …) read as a
	// navigable group rather than a single object: stacked-card thumbnail, a
	// member count, and a chevron that signals "opens a page". `hit.kind` is
	// referenced inline below so the discriminated union narrows member_count.

	function compact(n: number): string {
		if (n >= 1e6) return `${+(n / 1e6).toFixed(1)}M`;
		if (n >= 1e4) return `${Math.round(n / 1e3)}K`;
		if (n >= 1e3) return `${+(n / 1e3).toFixed(1)}K`;
		return n.toLocaleString();
	}
</script>

<!-- Combobox pattern: the row is an option, keyboard focus stays on the input
     (tabindex -1 keeps dozens of rows out of the tab order). -->
<button
	type="button"
	{id}
	role="option"
	aria-selected={active}
	tabindex={-1}
	class="w-full text-start px-4 py-2 flex items-center gap-3 transition-colors {active
		? 'bg-neutral-200 dark:bg-accent'
		: 'hover:bg-neutral-200 dark:hover:bg-accent'}"
	onmouseenter={onhover}
	onclick={onselect}
>
	<span class="relative size-9 shrink-0">
		{#if hit.kind === 'group'}
			<!-- offset cards behind the thumbnail to read as a stack -->
			<span class="absolute inset-0 translate-x-1 -translate-y-0.5 rounded-md bg-muted opacity-40"
			></span>
			<span class="absolute inset-0 translate-x-0.5 -translate-y-px rounded-md bg-muted opacity-70"
			></span>
		{/if}
		{#if thumbnail}
			<img
				src={thumbnail}
				alt=""
				loading="lazy"
				decoding="async"
				class="absolute inset-0 size-9 rounded-md object-cover bg-muted"
			/>
		{:else}
			<span class="absolute inset-0 size-9 rounded-md bg-muted"></span>
		{/if}
		{#if hit.kind === 'group'}
			<span
				class="absolute -end-1 -bottom-1 grid size-4 place-items-center rounded bg-popover text-foreground ring-2 ring-popover"
			>
				<LayersIcon class="size-2.5" />
			</span>
		{/if}
	</span>

	<span class="flex flex-col gap-0.5 min-w-0 flex-1">
		<span dir="auto" class="text-sm text-foreground truncate">{name}</span>
		{#if secondary}
			<span dir="auto" class="text-xs text-muted-foreground truncate">{secondary}</span>
		{/if}
	</span>

	{#if hit.kind === 'group'}
		<span class="flex shrink-0 items-center gap-1.5 text-muted-foreground">
			<span class="text-xs tabular-nums text-foreground">{compact(hit.member_count)}</span>
			<ChevronRightIcon class="size-4 rtl:rotate-180" />
		</span>
	{:else if metric}
		<span class="shrink-0 text-end font-mono text-xs tabular-nums text-muted-foreground">
			<span class="text-foreground">{metric.value}</span>{#if metric.unit}<span class="ms-0.5"
					>{metric.unit}</span
				>{/if}
		</span>
	{/if}
</button>
