<script lang="ts">
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import ChevronUpIcon from '@lucide/svelte/icons/chevron-up';
	import PauseIcon from '@lucide/svelte/icons/pause';
	import RewindIcon from '@lucide/svelte/icons/rewind';
	import type { SimClock } from '$lib/scene/state/clock.svelte';
	import { dateToJD, formatJulianDateTime } from '$lib/format/date';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import { getSettings } from '$lib/state/settings.svelte';
	import * as m from '$lib/paraglide/messages.js';
	import * as Popover from '$lib/components/ui/popover';
	import { Calendar } from '$lib/components/ui/calendar';
	import { type DateValue } from '@internationalized/date';
	import { untrack } from 'svelte';
	import {
		TIME_SCALES,
		TIME_DATE_OPTS,
		PICKER_MIN_DATE,
		PICKER_MAX_DATE
	} from '$lib/scene/time-scales';
	import {
		applyDateToClock,
		applyTimeToClock,
		clockTimeValue,
		jdToCalendarDate
	} from './clock-pickers';

	interface Props {
		clock: SimClock;
	}

	let { clock }: Props = $props();

	let pickerOpen = $state(false);
	let pickerValue = $state<DateValue | undefined>(undefined);
	let pickerPlaceholder = $state<DateValue | undefined>(undefined);

	$effect(() => {
		if (pickerOpen) {
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

	// Fixtures covering the variants that change rendered length: month
	// abbreviations, meridiem/hour boundaries, day digit count. Measured as
	// pixel width, not char count, which underestimates RTL/CJK/diacritics.
	const WIDTH_FIXTURES = [
		// month-abbreviation outliers
		new Date(Date.UTC(2026, 8, 30, 23, 59)), // Sep — often longest ("sept.", "syys", "сент.")
		new Date(Date.UTC(2026, 10, 30, 23, 59)), // Nov — longer than Sep in fi/some Slavic locales
		new Date(Date.UTC(2026, 9, 30, 23, 59)), // Oct — long in cs ("říj.")
		new Date(Date.UTC(2026, 1, 28, 23, 59)), // Feb — accented in fr/es ("févr.")
		// meridiem / hour boundaries (12h locales)
		new Date(Date.UTC(2026, 8, 30, 0, 0)), // 12:00 AM
		new Date(Date.UTC(2026, 8, 30, 12, 0)), // 12:00 PM
		new Date(Date.UTC(2026, 8, 30, 1, 5)),
		// 1-digit day
		new Date(Date.UTC(2026, 8, 9, 23, 59))
	];

	const settings = getSettings();
	let dateLabel = $derived(formatJulianDateTime(shownJd, TIME_DATE_OPTS));

	// Pins the label's min-width to the widest fixture so the bar doesn't
	// jitter as the clock ticks.
	let dateMinPx = $state(0);

	$effect(() => {
		const loc = getLocale();
		// Re-measure when the user toggles date-format or clock: both can
		// change the rendered width.
		void settings.resolvedDateFormat;
		void settings.resolvedHour12;
		const el = document.createElement('span');
		el.className = 'inline-block font-mono tabular-nums whitespace-nowrap text-xs';
		el.style.cssText =
			'position: absolute; left: -9999px; top: 0; visibility: hidden; pointer-events: none;';
		document.body.appendChild(el);
		try {
			let max = 0;
			for (const d of WIDTH_FIXTURES) {
				el.textContent = formatJulianDateTime(dateToJD(d), TIME_DATE_OPTS);
				const w = el.getBoundingClientRect().width;
				if (w > max) max = w;
			}
			dateMinPx = Math.ceil(max);
		} finally {
			el.remove();
		}
		// Touch loc so the effect tracks locale changes too.
		void loc;
	});
</script>

<div
	class="fixed bottom-[calc(var(--safe-bottom)_+_1.25rem)] left-1/2 -translate-x-1/2 z-10
		hidden md:flex pointer-events-auto items-baseline gap-2 p-2 rounded-full
		bg-primary-foreground/95 backdrop-blur text-primary
		shadow-lg text-xs"
>
	<button
		type="button"
		class="inline-flex items-center justify-center self-center h-8 px-2 rounded-md transition-colors cursor-pointer
			{clock.direction === -1 ? 'bg-primary text-primary-foreground' : 'hover:bg-primary/10'}"
		onclick={() => clock.toggleDirection()}
		aria-label={m.time_reverse()}
		aria-pressed={clock.direction === -1}
		title={m.time_reverse()}
	>
		<RewindIcon class="size-4" />
	</button>

	<button
		type="button"
		class="inline-flex items-center justify-center self-center h-8 px-2 rounded-md transition-colors cursor-pointer
			{clock.playing ? 'hover:bg-primary/10' : 'bg-primary text-primary-foreground'}"
		onclick={() => (clock.playing ? clock.pause() : clock.play())}
		aria-label={clock.playing ? m.time_pause() : m.time_play()}
		title={clock.playing ? m.time_pause() : m.time_play()}
	>
		<PauseIcon class="size-4" />
	</button>

	{#each TIME_SCALES as { label, value } (value)}
		<button
			type="button"
			class="inline-flex items-center justify-center h-8 px-2 rounded-md whitespace-nowrap transition-colors cursor-pointer
				{Math.abs(clock.timeScale) === value
				? 'bg-primary text-primary-foreground'
				: 'hover:bg-primary/10'}"
			aria-pressed={Math.abs(clock.timeScale) === value}
			onclick={() => clock.setTimeScale(value)}
		>
			{label()}
		</button>
	{/each}

	<span class="self-stretch w-px bg-primary/20 mx-1" aria-hidden="true"></span>

	<Popover.Root bind:open={pickerOpen}>
		<Popover.Trigger
			class="inline-flex items-center justify-center gap-1 h-8 px-2 font-mono tabular-nums
				rounded-md hover:bg-primary/10 transition-colors cursor-pointer"
			title={m.time_pick_date()}
		>
			<span
				class="inline-block text-center"
				style={dateMinPx ? `min-width: ${dateMinPx}px` : undefined}
			>
				{dateLabel}
			</span>
			{#if pickerOpen}
				<ChevronDownIcon class="size-3.5 shrink-0 opacity-50" />
			{:else}
				<ChevronUpIcon class="size-3.5 shrink-0 opacity-50" />
			{/if}
		</Popover.Trigger>
		<Popover.Content class="w-auto p-0" align="center" sideOffset={8}>
			<Calendar
				type="single"
				bind:value={pickerValue}
				bind:placeholder={pickerPlaceholder}
				onValueChange={handleDateChange}
				captionLayout="dropdown"
				locale={getLocale()}
				minValue={PICKER_MIN_DATE}
				maxValue={PICKER_MAX_DATE}
			/>
			<div class="border-t p-3">
				<input
					type="time"
					value={timeValue}
					onchange={handleTimeChange}
					aria-label={m.time_pick_time()}
					class="h-8 w-full rounded-md border bg-transparent px-2 font-mono tabular-nums text-sm
						scheme-light-dark
						focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring"
				/>
			</div>
		</Popover.Content>
	</Popover.Root>

	<button
		type="button"
		class="inline-flex items-center justify-center h-8 px-2 rounded-md hover:bg-primary/10 cursor-pointer"
		onclick={() => clock.now()}
		title={m.time_now_tooltip()}
	>
		{m.time_now()}
	</button>
</div>
