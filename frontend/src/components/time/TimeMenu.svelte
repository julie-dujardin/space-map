<script lang="ts">
	import CalendarIcon from '@lucide/svelte/icons/calendar';
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import PauseIcon from '@lucide/svelte/icons/pause';
	import RewindIcon from '@lucide/svelte/icons/rewind';
	import { Calendar } from '$lib/components/ui/calendar';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import { type DateValue } from '@internationalized/date';
	import { formatJulianDateTime } from '$lib/format/date';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import * as m from '$lib/paraglide/messages.js';
	import {
		TIME_DATE_OPTS,
		TIME_SCALES,
		PICKER_MIN_DATE,
		PICKER_MAX_DATE
	} from '$lib/scene/time-scales';
	import type { SimClock } from '$lib/scene/state/clock.svelte';
	import { untrack } from 'svelte';
	import {
		applyDateToClock,
		applyTimeToClock,
		clockTimeValue,
		jdToCalendarDate
	} from './clock-pickers';

	/** The stacked time controls shared by the phone sheet and the narrow-desktop
	 *  popover. Expects 1rem of horizontal padding around it: the scale strip
	 *  bleeds into it so the chips scroll edge to edge. */
	interface Props {
		clock: SimClock;
	}

	let { clock }: Props = $props();

	let showCalendar = $state(false);
	let pickerValue = $state<DateValue | undefined>(undefined);
	let pickerPlaceholder = $state<DateValue | undefined>(undefined);

	$effect(() => {
		if (showCalendar) {
			const cd = untrack(() => jdToCalendarDate(clock.jd));
			pickerValue = cd;
			pickerPlaceholder = cd;
		}
	});

	const handleDateChange = (v: DateValue | undefined) => applyDateToClock(clock, v);
	const handleTimeChange = (e: Event) => applyTimeToClock(clock, e);
	// The label shows minutes; quantising to the second stops the formatter
	// running on every frame of a 1x clock.
	const shownJd = $derived(Math.floor(clock.jd * 86400) / 86400);
	let timeValue = $derived(clockTimeValue(shownJd));

	let dateLabel = $derived(formatJulianDateTime(shownJd, TIME_DATE_OPTS));

	// The inline year-select doesn't see minValue/maxValue and would otherwise
	// fall back to a hardcoded [currentYear-100, currentYear] window.
	const PICKER_YEARS = Array.from(
		{ length: PICKER_MAX_DATE.year - PICKER_MIN_DATE.year + 1 },
		(_, i) => PICKER_MIN_DATE.year + i
	);
</script>

<div class="flex flex-col gap-4">
	<button
		type="button"
		class="flex w-full items-center justify-between gap-3 rounded-lg border bg-background px-3 py-3
			text-start transition-colors hover:bg-primary/5 cursor-pointer"
		onclick={() => (showCalendar = !showCalendar)}
		title={m.time_pick_date()}
		aria-expanded={showCalendar}
	>
		<span class="flex min-w-0 items-center gap-2.5">
			<CalendarIcon class="size-5 shrink-0 opacity-70" />
			<span class="truncate font-mono tabular-nums text-base">{dateLabel}</span>
		</span>
		<ChevronDownIcon
			class="size-4 shrink-0 opacity-50 transition-transform {showCalendar ? 'rotate-180' : ''}"
		/>
	</button>

	{#if showCalendar}
		<div class="w-full shrink-0 overflow-hidden rounded-md border bg-background">
			<!-- The columns share the container's width rather than each taking a fixed
			     cell, so the day targets are as big as the space allows. Each day
			     keeps its own size and centres in the column it was given. -->
			<Calendar
				class="w-full [&_td]:w-[calc(100%/7)] [&_th]:w-[calc(100%/7)] [&_[data-bits-day]]:mx-auto"
				type="single"
				bind:value={pickerValue}
				bind:placeholder={pickerPlaceholder}
				onValueChange={handleDateChange}
				captionLayout="dropdown-inline"
				locale={getLocale()}
				minValue={PICKER_MIN_DATE}
				maxValue={PICKER_MAX_DATE}
				years={PICKER_YEARS}
			/>
			<div class="border-t p-3">
				<input
					type="time"
					value={timeValue}
					onchange={handleTimeChange}
					aria-label={m.time_pick_time()}
					class="h-9 w-full rounded-md border bg-transparent px-2 font-mono tabular-nums text-base
						scheme-light-dark
						focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring"
				/>
			</div>
		</div>
	{/if}

	<div class="flex items-center gap-3">
		<button
			type="button"
			class="inline-flex items-center justify-center w-11 h-11 rounded-full transition-colors cursor-pointer
				{clock.direction === -1
				? 'bg-primary text-primary-foreground'
				: 'bg-primary/10 hover:bg-primary/20 text-primary'}"
			onclick={() => clock.toggleDirection()}
			aria-label={m.time_reverse()}
			aria-pressed={clock.direction === -1}
			title={m.time_reverse()}
		>
			<RewindIcon class="size-5" />
		</button>

		<button
			type="button"
			class="inline-flex items-center justify-center w-11 h-11 rounded-full transition-colors cursor-pointer
				{clock.playing
				? 'bg-primary/10 hover:bg-primary/20 text-primary'
				: 'bg-primary text-primary-foreground'}"
			onclick={() => (clock.playing ? clock.pause() : clock.play())}
			aria-label={clock.playing ? m.time_pause() : m.time_play()}
			title={clock.playing ? m.time_pause() : m.time_play()}
		>
			<PauseIcon class="size-5" />
		</button>

		<button
			type="button"
			class="inline-flex items-center justify-center h-11 px-4 rounded-full
				bg-primary/10 hover:bg-primary/20 text-primary text-sm font-medium transition-colors cursor-pointer"
			onclick={() => clock.now()}
			title={m.time_now_tooltip()}
		>
			{m.time_now()}
		</button>
	</div>

	<ScrollArea orientation="horizontal" class="-mx-4" scrollbarXClasses="h-1.5">
		<div class="flex items-center gap-2 px-4 pb-3">
			{#each TIME_SCALES as { label, value } (value)}
				<button
					type="button"
					class="inline-flex items-center justify-center h-9 px-3 rounded-full whitespace-nowrap text-sm transition-colors cursor-pointer
						{Math.abs(clock.timeScale) === value
						? 'bg-primary text-primary-foreground'
						: 'bg-primary/10 hover:bg-primary/20 text-primary'}"
					aria-pressed={Math.abs(clock.timeScale) === value}
					onclick={() => clock.setTimeScale(value)}
				>
					{label()}
				</button>
			{/each}
		</div>
	</ScrollArea>
</div>
