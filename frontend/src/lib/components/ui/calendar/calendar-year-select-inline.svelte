<script lang="ts">
	import { DateFormatter, type DateValue } from '@internationalized/date';
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import { cn } from '$lib/utils.js';
	import { extendedYear, withExtendedYear, yearLabel } from '$lib/time/calendars/picker';
	import { tick } from 'svelte';

	type YearFormat = Intl.DateTimeFormatOptions['year'] | ((year: number) => string);

	interface Props {
		years?: number[];
		yearFormat?: YearFormat;
		locale: string;
		/** The calendar `years` count in; numbered through its epoch, 0 and below
		 *  before it. */
		calendar?: string;
		placeholder: DateValue | undefined;
		onSelect: (newPlaceholder: DateValue) => void;
		/** Names the field that narrows the list as a year is typed. */
		searchLabel?: string;
		class?: string;
	}

	let {
		years,
		yearFormat = 'numeric',
		locale,
		calendar = 'gregory',
		placeholder,
		onSelect,
		searchLabel,
		class: className
	}: Props = $props();

	let open = $state(false);
	let query = $state('');
	let triggerRef = $state<HTMLButtonElement | null>(null);
	let menuRef = $state<HTMLDivElement | null>(null);
	let listRef = $state<HTMLDivElement | null>(null);

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
		if (yearFormat === 'numeric') return yearLabel(calendar, locale, yearValue);
		const dt = new Date(yearValue, 0, 1);
		return new DateFormatter(locale, { year: yearFormat }).format(dt);
	}

	let yearList = $derived(years ?? DEFAULT_YEARS);
	let items = $derived(yearList.map((value) => ({ value, label: formatYear(value) })));
	let selectedValue = $derived(placeholder ? extendedYear(placeholder) : new Date().getFullYear());
	let selectedLabel = $derived(items.find((i) => i.value === selectedValue)?.label ?? '');
	// Centuries of years are too many to scroll through: typing the first
	// digits narrows the list.
	let shown = $derived.by(() => {
		const q = query.trim();
		if (!q) return items;
		return items.filter((i) => String(i.value).startsWith(q) || i.label.startsWith(q));
	});
	let rangeHint = $derived(
		items.length > 1 ? `${items[0].label}–${items[items.length - 1].label}` : ''
	);

	function pick(value: number) {
		if (!placeholder) {
			open = false;
			return;
		}
		onSelect(withExtendedYear(placeholder, value));
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
		query = '';
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
			class="absolute top-full start-0 z-20 mt-1 flex max-h-60 min-w-full flex-col rounded-md border bg-popover text-popover-foreground shadow-md"
		>
			<div class="shrink-0 p-1">
				<input
					type="text"
					inputmode="numeric"
					bind:value={query}
					oninput={() => listRef && (listRef.scrollTop = 0)}
					placeholder={rangeHint}
					aria-label={searchLabel}
					onkeydown={(e) => {
						if (e.key === 'Enter' && shown.length > 0) pick(shown[0].value);
					}}
					class="h-8 w-full min-w-24 rounded-md border bg-transparent px-2 text-sm tabular-nums
						focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring"
				/>
			</div>
			<div bind:this={listRef} role="listbox" class="min-h-0 overflow-y-auto pb-1">
				{#each shown as item (item.value)}
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
		</div>
	{/if}
</span>
