<script lang="ts">
	import { DateFormatter, type DateValue } from '@internationalized/date';
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import { cn } from '$lib/utils.js';

	type MonthFormat = Intl.DateTimeFormatOptions['month'] | ((month: number) => string);

	interface Props {
		months?: number[];
		monthFormat?: MonthFormat;
		locale: string;
		placeholder: DateValue | undefined;
		monthIndex: number;
		onSelect: (newPlaceholder: DateValue) => void;
		class?: string;
	}

	let {
		months = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
		monthFormat = 'long',
		locale,
		placeholder,
		monthIndex,
		onSelect,
		class: className
	}: Props = $props();

	let open = $state(false);
	let triggerRef = $state<HTMLButtonElement | null>(null);
	let menuRef = $state<HTMLDivElement | null>(null);

	function formatMonth(monthValue: number): string {
		if (typeof monthFormat === 'function') return monthFormat(monthValue);
		const dt = new Date(2000, monthValue - 1, 1);
		return new DateFormatter(locale, { month: monthFormat }).format(dt);
	}

	let items = $derived(months.map((value) => ({ value, label: formatMonth(value) })));
	let selectedValue = $derived(placeholder ? placeholder.month : 1);
	let selectedLabel = $derived(items.find((i) => i.value === selectedValue)?.label ?? '');

	function pick(value: number) {
		if (!placeholder) {
			open = false;
			return;
		}
		const next = placeholder.set({ month: value }).subtract({ months: monthIndex });
		onSelect(next);
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
