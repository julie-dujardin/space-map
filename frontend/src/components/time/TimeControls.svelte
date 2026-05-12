<script lang="ts">
	import PauseIcon from '@lucide/svelte/icons/pause';
	import RewindIcon from '@lucide/svelte/icons/rewind';
	import type { SimClock } from '$lib/scene/clock.svelte';
	import { dateToJD, jdToDate } from '$lib/format/date';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import * as m from '$lib/paraglide/messages.js';
	import * as Popover from '$lib/components/ui/popover';
	import { Calendar } from '$lib/components/ui/calendar';
	import { CalendarDate, type DateValue } from '@internationalized/date';
	import { untrack } from 'svelte';
	import { TIME_SCALES, TIME_DATE_OPTS } from '$lib/scene/time-scales';

	interface Props {
		clock: SimClock;
	}

	let { clock }: Props = $props();

	let pickerOpen = $state(false);
	let pickerValue = $state<DateValue | undefined>(undefined);
	let pickerPlaceholder = $state<DateValue | undefined>(undefined);

	function jdToCalendarDate(jd: number): CalendarDate {
		const d = jdToDate(jd);
		return new CalendarDate(d.getFullYear(), d.getMonth() + 1, d.getDate());
	}

	$effect(() => {
		if (pickerOpen) {
			const cd = untrack(() => jdToCalendarDate(clock.jd));
			pickerValue = cd;
			pickerPlaceholder = cd;
		}
	});

	function handleDateChange(v: DateValue | undefined) {
		if (!v) return;
		const next = jdToDate(clock.jd);
		next.setFullYear(v.year, v.month - 1, v.day);
		clock.setJD(dateToJD(next));
	}

	let timeValue = $derived.by(() => {
		const d = jdToDate(clock.jd);
		return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
	});

	function handleTimeChange(e: Event) {
		const match = (e.currentTarget as HTMLInputElement).value.match(/^(\d{2}):(\d{2})$/);
		if (!match) return;
		const next = jdToDate(clock.jd);
		next.setHours(Number(match[1]), Number(match[2]), 0, 0);
		clock.setJD(dateToJD(next));
	}

	// Width fixtures: cover the variants that change rendered length —
	// month-abbreviation outliers, meridiem/hour boundaries, and day digit count.
	// Char counting underestimates RTL/CJK/diacritics, so we measure actual
	// pixel width instead (see effect below).
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

	let dateLabel = $derived(jdToDate(clock.jd).toLocaleString(getLocale(), TIME_DATE_OPTS));

	// Measure the widest fixture against an off-screen span that mirrors the
	// trigger's typography + padding, then pin the trigger's min-width to it.
	// Pixel measurement handles non-Latin scripts and proportional fonts
	// correctly; char counting does not.
	// TODO: recompute when the language switcher lands.
	let dateMinPx = $state(0);

	$effect(() => {
		const loc = getLocale();
		const el = document.createElement('span');
		el.className =
			'inline-flex items-center h-8 px-2 font-mono tabular-nums whitespace-nowrap text-xs';
		el.style.cssText =
			'position: absolute; left: -9999px; top: 0; visibility: hidden; pointer-events: none;';
		document.body.appendChild(el);
		try {
			let max = 0;
			for (const d of WIDTH_FIXTURES) {
				el.textContent = d.toLocaleString(loc, TIME_DATE_OPTS);
				const w = el.getBoundingClientRect().width;
				if (w > max) max = w;
			}
			dateMinPx = Math.ceil(max);
		} finally {
			el.remove();
		}
	});
</script>

<div
	class="fixed bottom-5 left-1/2 -translate-x-1/2 z-10
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
			onclick={() => clock.setTimeScale(value)}
		>
			{label()}
		</button>
	{/each}

	<span class="self-stretch w-px bg-primary/20 mx-1" aria-hidden="true"></span>

	<Popover.Root bind:open={pickerOpen}>
		<Popover.Trigger
			class="inline-flex items-center justify-center h-8 px-2 font-mono tabular-nums
				rounded-md hover:bg-primary/10 transition-colors cursor-pointer"
			style={dateMinPx ? `min-width: ${dateMinPx}px` : undefined}
			title={m.time_pick_date()}
		>
			{dateLabel}
		</Popover.Trigger>
		<Popover.Content class="w-auto p-0" align="center" sideOffset={8}>
			<Calendar
				type="single"
				bind:value={pickerValue}
				bind:placeholder={pickerPlaceholder}
				onValueChange={handleDateChange}
				captionLayout="dropdown"
				locale={getLocale()}
			/>
			<label class="flex items-center justify-between gap-3 border-t px-3 py-2 text-sm">
				<span class="text-muted-foreground">{m.time_pick_time()}</span>
				<input
					type="time"
					value={timeValue}
					onchange={handleTimeChange}
					class="h-8 rounded-md border bg-transparent px-2 font-mono tabular-nums text-sm
						scheme-light-dark
						focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
				/>
			</label>
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
