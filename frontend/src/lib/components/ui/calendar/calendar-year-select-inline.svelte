<script lang="ts">
	import { DateFormatter, type DateValue } from '@internationalized/date';
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import { cn } from '$lib/utils.js';
	import { tick } from 'svelte';

	type YearFormat = Intl.DateTimeFormatOptions['year'] | ((year: number) => string);

	interface Props {
		years?: number[];
		yearFormat?: YearFormat;
		locale: string;
		placeholder: DateValue | undefined;
		onSelect: (newPlaceholder: DateValue) => void;
		class?: string;
	}

	let {
		years,
		yearFormat = 'numeric',
		locale,
		placeholder,
		onSelect,
		class: className
	}: Props = $props();

	let open = $state(false);
	let triggerRef = $state<HTMLButtonElement | null>(null);
	let menuRef = $state<HTMLDivElement | null>(null);

	const DEFAULT_YEARS = (() => {
		const cy = new Date().getFullYear();
		// Match bits-ui's default range so the inline variant doesn't surprise
		// callers who relied on the wrapped Calendar's behaviour.
		const arr: number[] = [];
		for (let y = cy - 100; y <= cy; y++) arr.push(y);
		return arr;
	})();

	function formatYear(yearValue: number): string {
		if (typeof yearFormat === 'function') return yearFormat(yearValue);
		const dt = new Date(yearValue, 0, 1);
		return new DateFormatter(locale, { year: yearFormat }).format(dt);
	}

	let yearList = $derived(years ?? DEFAULT_YEARS);
	let items = $derived(yearList.map((value) => ({ value, label: formatYear(value) })));
	let selectedValue = $derived(placeholder ? placeholder.year : new Date().getFullYear());
	let selectedLabel = $derived(items.find((i) => i.value === selectedValue)?.label ?? '');

	function pick(value: number) {
		if (!placeholder) {
			open = false;
			return;
		}
		onSelect(placeholder.set({ year: value }));
		open = false;
		triggerRef?.focus();
	}

	function handleDocClick(e: MouseEvent) {
		if (!open) return;
		const t = e.target as Node | null;
		if (!t) return;
		if (triggerRef?.contains(t) || menuRef?.contains(t)) return;
		open = false;
	}

	function handleKey(e: KeyboardEvent) {
		if (e.key === 'Escape' && open) {
			open = false;
			triggerRef?.focus();
		}
	}

	$effect(() => {
		if (!open) return;
		document.addEventListener('mousedown', handleDocClick);
		document.addEventListener('keydown', handleKey);
		// Scroll the selected year into view once the menu mounts.
		(async () => {
			await tick();
			const sel = menuRef?.querySelector('[aria-selected="true"]') as HTMLElement | null;
			sel?.scrollIntoView({ block: 'center' });
		})();
		return () => {
			document.removeEventListener('mousedown', handleDocClick);
			document.removeEventListener('keydown', handleKey);
		};
	});
</script>

<span class={cn('relative inline-flex', className)}>
	<button
		bind:this={triggerRef}
		type="button"
		onclick={() => (open = !open)}
		aria-haspopup="listbox"
		aria-expanded={open}
		class="border-input bg-background hover:bg-accent flex h-(--cell-size) items-center gap-1 rounded-md border ps-2 pe-1 text-sm font-medium shadow-xs transition-colors cursor-pointer"
	>
		<span>{selectedLabel}</span>
		<ChevronDownIcon class="size-3.5 text-muted-foreground" />
	</button>

	{#if open}
		<div
			bind:this={menuRef}
			role="listbox"
			class="absolute top-full start-0 z-20 mt-1 max-h-60 min-w-full overflow-y-auto rounded-md border bg-popover text-popover-foreground shadow-md py-1"
		>
			{#each items as item (item.value)}
				<button
					type="button"
					role="option"
					aria-selected={item.value === selectedValue}
					onclick={() => pick(item.value)}
					class="block w-full text-start px-3 py-1.5 text-sm cursor-pointer transition-colors
						{item.value === selectedValue
						? 'bg-accent text-accent-foreground'
						: 'hover:bg-accent hover:text-accent-foreground'}"
				>
					{item.label}
				</button>
			{/each}
		</div>
	{/if}
</span>
