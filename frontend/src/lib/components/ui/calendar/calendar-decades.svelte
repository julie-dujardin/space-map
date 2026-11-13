<script lang="ts">
	import ChevronLeftIcon from '@lucide/svelte/icons/chevron-left';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import type { DateValue } from '@internationalized/date';
	import { tick } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import { buttonVariants } from '$lib/components/ui/button/index.js';
	import type { ClassValue } from 'clsx';
	import { cn } from '$lib/utils.js';
	import { calendarDateFormat, FRENCH_REPUBLICAN } from '$lib/time/calendars';
	import { pickerDateToUtcNoon, toPickerDate } from '$lib/time/calendars/picker';
	import { decadeDayNames } from '$lib/time/calendars/republican';
	import CalendarMonthSelectInline from './calendar-month-select-inline.svelte';
	import CalendarYearSelectInline from './calendar-year-select-inline.svelte';

	/**
	 * The Republican month as the Republic drew it: three décades of ten days,
	 * primidi to décadi, every month the same thirty-cell block with no days
	 * spilling in from its neighbours; then the complementary days, five or
	 * six, on a line of their own. bits-ui's grid is built on the seven-day
	 * week, so this stands in for it, with the same caption and the same keys.
	 */
	interface Props {
		value?: DateValue;
		placeholder?: DateValue;
		onValueChange?: (value: DateValue | undefined) => void;
		minValue?: DateValue;
		maxValue?: DateValue;
		years?: number[];
		locale: string;
		yearSearchLabel?: string;
		class?: ClassValue | null;
	}

	let {
		value = $bindable(),
		placeholder = $bindable(),
		onValueChange,
		minValue,
		maxValue,
		years,
		locale,
		yearSearchLabel,
		class: className
	}: Props = $props();

	const DAYS_PER_DECADE = 10;

	const shown = $derived(placeholder ?? value);
	const monthStart = $derived(shown?.set({ day: 1 }));
	const days = $derived.by(() => {
		if (!monthStart) return [];
		const count = monthStart.calendar.getDaysInMonth(monthStart);
		return Array.from({ length: count }, (_, i) => monthStart.set({ day: i + 1 }));
	});
	/** The complementary days: not a décade, so no décade's columns over them. */
	const complementary = $derived(days.length < DAYS_PER_DECADE);
	const rows = $derived.by(() => {
		const out: DateValue[][] = [];
		for (let i = 0; i < days.length; i += DAYS_PER_DECADE) {
			out.push(days.slice(i, i + DAYS_PER_DECADE));
		}
		return out;
	});

	const columns = $derived(decadeDayNames(locale));
	const dayLabel = $derived(
		calendarDateFormat(locale, FRENCH_REPUBLICAN, {
			weekday: 'long',
			year: 'numeric',
			month: 'long',
			day: 'numeric',
			timeZone: 'UTC'
		})
	);
	/** A complementary day is its feast ("jour de la Vertu"), not a number. */
	const feastLabel = $derived(
		calendarDateFormat(locale, FRENCH_REPUBLICAN, {
			month: 'long',
			day: 'numeric',
			timeZone: 'UTC'
		})
	);
	const monthLabel = $derived(
		calendarDateFormat(locale, FRENCH_REPUBLICAN, {
			year: 'numeric',
			month: 'long',
			timeZone: 'UTC'
		})
	);

	const today = (() => {
		const now = new Date();
		return toPickerDate(now.getFullYear(), now.getMonth() + 1, now.getDate(), FRENCH_REPUBLICAN);
	})();

	const same = (a: DateValue | undefined, b: DateValue | undefined) =>
		!!a && !!b && a.compare(b) === 0;
	const outOfRange = (date: DateValue) =>
		(!!minValue && date.compare(minValue) < 0) || (!!maxValue && date.compare(maxValue) > 0);

	/** The day the keys move from: the chosen one where it is on show. */
	let focused = $state<DateValue | undefined>(undefined);
	const anchor = $derived.by(() => {
		const inMonth = (d: DateValue | undefined) =>
			!!d && !!monthStart && d.month === monthStart.month && d.year === monthStart.year;
		if (inMonth(focused)) return focused;
		if (inMonth(value)) return value;
		return monthStart;
	});

	let gridEl = $state<HTMLDivElement | null>(null);

	function pick(date: DateValue): void {
		if (outOfRange(date)) return;
		value = date;
		focused = date;
		onValueChange?.(date);
	}

	function clamp(date: DateValue): DateValue {
		if (minValue && date.compare(minValue) < 0) return minValue;
		if (maxValue && date.compare(maxValue) > 0) return maxValue;
		return date;
	}

	function showMonth(delta: number): void {
		if (!monthStart) return;
		placeholder = clamp(monthStart.add({ months: delta }));
	}

	const prevDisabled = $derived(
		!!minValue && !!monthStart && monthStart.subtract({ days: 1 }).compare(minValue) < 0
	);
	const nextDisabled = $derived(
		!!maxValue && !!monthStart && monthStart.add({ months: 1 }).compare(maxValue) > 0
	);

	async function moveFocus(to: DateValue): Promise<void> {
		const next = clamp(to);
		focused = next;
		if (monthStart && (next.month !== monthStart.month || next.year !== monthStart.year)) {
			placeholder = next;
		}
		await tick();
		gridEl?.querySelector<HTMLButtonElement>('button[tabindex="0"]')?.focus();
	}

	function onKey(e: KeyboardEvent): void {
		const from = anchor;
		if (!from) return;
		const rtl = gridEl ? getComputedStyle(gridEl).direction === 'rtl' : false;
		const sideways = rtl ? -1 : 1;
		const inDecade = (from.day - 1) % DAYS_PER_DECADE;
		let to: DateValue | undefined;
		switch (e.key) {
			case 'ArrowRight':
				to = from.add({ days: sideways });
				break;
			case 'ArrowLeft':
				to = from.subtract({ days: sideways });
				break;
			case 'ArrowDown':
				to = from.add({ days: DAYS_PER_DECADE });
				break;
			case 'ArrowUp':
				to = from.subtract({ days: DAYS_PER_DECADE });
				break;
			case 'Home':
				to = from.subtract({ days: inDecade });
				break;
			case 'End':
				to = from.add({ days: Math.min(DAYS_PER_DECADE - 1 - inDecade, days.length - from.day) });
				break;
			case 'PageUp':
				to = from.subtract({ months: 1 });
				break;
			case 'PageDown':
				to = from.add({ months: 1 });
				break;
			default:
				return;
		}
		e.preventDefault();
		void moveFocus(to);
	}
</script>

<div
	class={cn(
		'bg-background p-2 [--cell-radius:var(--radius-md)] [--cell-size:--spacing(7)]',
		className
	)}
>
	<div class="relative flex flex-col gap-4">
		<div class="flex h-(--cell-size) w-full items-center justify-between gap-1">
			<button
				type="button"
				class={cn(
					buttonVariants({ variant: 'ghost' }),
					'size-(--cell-size) bg-transparent p-0 select-none disabled:opacity-50'
				)}
				aria-label={m.calendar_prev_month()}
				disabled={prevDisabled}
				onclick={() => showMonth(-1)}
			>
				<ChevronLeftIcon class="size-4 rtl:rotate-180" />
			</button>
			<div class="flex items-center justify-center gap-1.5 text-sm font-medium">
				<CalendarMonthSelectInline
					monthFormat="long"
					{locale}
					calendar={FRENCH_REPUBLICAN}
					placeholder={shown}
					monthIndex={0}
					onSelect={(next) => (placeholder = clamp(next))}
				/>
				<CalendarYearSelectInline
					{years}
					{locale}
					calendar={FRENCH_REPUBLICAN}
					placeholder={shown}
					searchLabel={yearSearchLabel}
					onSelect={(next) => (placeholder = clamp(next))}
				/>
			</div>
			<button
				type="button"
				class={cn(
					buttonVariants({ variant: 'ghost' }),
					'size-(--cell-size) bg-transparent p-0 select-none disabled:opacity-50'
				)}
				aria-label={m.calendar_next_month()}
				disabled={nextDisabled}
				onclick={() => showMonth(1)}
			>
				<ChevronRightIcon class="size-4 rtl:rotate-180" />
			</button>
		</div>

		<div
			bind:this={gridEl}
			role="grid"
			tabindex="-1"
			aria-label={monthStart ? monthLabel.format(pickerDateToUtcNoon(monthStart)) : undefined}
			class="grid gap-y-2 {complementary
				? 'grid-cols-1'
				: 'grid-cols-[repeat(10,minmax(var(--cell-size),1fr))]'}"
			onkeydown={onKey}
		>
			{#if !complementary}
				<div role="row" class="contents">
					{#each columns as name (name)}
						<div
							role="columnheader"
							title={name}
							class="text-muted-foreground text-center text-[0.8rem] font-normal select-none"
						>
							<abbr class="no-underline" title={name}>{name.slice(0, 3)}</abbr>
						</div>
					{/each}
				</div>
			{/if}
			{#each rows as row, r (r)}
				<div role="row" class="contents">
					{#each row as date (date.day)}
						{@const selected = same(date, value)}
						{@const disabled = outOfRange(date)}
						<div role="gridcell" aria-selected={selected} class="flex justify-center">
							<button
								type="button"
								tabindex={same(date, anchor) ? 0 : -1}
								aria-label={dayLabel.format(pickerDateToUtcNoon(date))}
								{disabled}
								data-today={same(date, today) ? '' : undefined}
								data-selected={selected ? '' : undefined}
								data-decadi={(date.day - 1) % DAYS_PER_DECADE === DAYS_PER_DECADE - 1
									? ''
									: undefined}
								class="flex {complementary
									? 'h-(--cell-size) w-full justify-start px-2'
									: 'size-(--cell-size) justify-center'} cursor-pointer items-center rounded-(--cell-radius) text-sm leading-none tabular-nums select-none
									not-data-selected:hover:bg-accent/50 not-data-selected:hover:text-accent-foreground
									[&[data-today]:not([data-selected])]:bg-accent [&[data-today]:not([data-selected])]:text-accent-foreground
									data-[selected]:bg-primary data-[selected]:text-primary-foreground
									[&[data-decadi]:not([data-selected])]:font-semibold
									disabled:pointer-events-none disabled:text-muted-foreground disabled:opacity-50
									focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
								onclick={() => pick(date)}
								onfocus={() => (focused = date)}
							>
								{complementary ? feastLabel.format(pickerDateToUtcNoon(date)) : date.day}
							</button>
						</div>
					{/each}
				</div>
			{/each}
		</div>
	</div>
</div>
