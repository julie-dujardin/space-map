<script lang="ts">
	import { Drawer as Vaul } from 'vaul-svelte';
	import ClockIcon from '@lucide/svelte/icons/clock';
	import CalendarIcon from '@lucide/svelte/icons/calendar';
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import PauseIcon from '@lucide/svelte/icons/pause';
	import RewindIcon from '@lucide/svelte/icons/rewind';
	import XIcon from '@lucide/svelte/icons/x';
	import { Calendar } from '$lib/components/ui/calendar';
	import { Button } from '$lib/components/ui/button/index.js';
	import { CalendarDate, type DateValue } from '@internationalized/date';
	import { dateToJD, jdToDate, formatJulianDateTime } from '$lib/format/date';
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

	interface Props {
		clock: SimClock;
	}

	let { clock }: Props = $props();

	let open = $state(false);
	let showCalendar = $state(false);
	let pickerValue = $state<DateValue | undefined>(undefined);
	let pickerPlaceholder = $state<DateValue | undefined>(undefined);

	function jdToCalendarDate(jd: number): CalendarDate {
		const d = jdToDate(jd);
		return new CalendarDate(d.getFullYear(), d.getMonth() + 1, d.getDate());
	}

	$effect(() => {
		if (showCalendar) {
			const cd = untrack(() => jdToCalendarDate(clock.jd));
			pickerValue = cd;
			pickerPlaceholder = cd;
		}
	});

	$effect(() => {
		if (!open) showCalendar = false;
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

	let dateLabel = $derived(formatJulianDateTime(clock.jd, TIME_DATE_OPTS));
	let activeScale = $derived(
		TIME_SCALES.find((s) => s.value === Math.abs(clock.timeScale)) ?? TIME_SCALES[0]
	);

	// The inline year-select doesn't see minValue/maxValue and would otherwise
	// fall back to a hardcoded [currentYear-100, currentYear] window.
	const PICKER_YEARS = Array.from(
		{ length: PICKER_MAX_DATE.year - PICKER_MIN_DATE.year + 1 },
		(_, i) => PICKER_MIN_DATE.year + i
	);
</script>

<button
	type="button"
	onclick={() => (open = true)}
	class="pointer-events-auto flex items-center justify-center
		w-12 h-12 rounded-full
		bg-white hover:bg-white/80
		text-black transition-colors cursor-pointer"
	title={m.time_header()}
	aria-label={m.time_header()}
>
	<ClockIcon class="size-7" />
</button>

<Vaul.Root bind:open shouldScaleBackground={false}>
	<Vaul.Portal>
		<Vaul.Overlay class="fixed inset-0 z-[60] bg-black/40" />
		<Vaul.Content
			class="fixed inset-x-0 bottom-0 z-[61] flex flex-col rounded-t-xl border-t bg-background shadow-lg outline-none max-h-[90dvh]"
		>
			<div class="flex flex-col items-center gap-2 px-4 pt-3 pb-2">
				<div class="h-1 w-10 rounded-full bg-muted-foreground/40"></div>
				<div class="flex w-full items-center justify-between">
					<Vaul.Title class="text-sm font-semibold">{m.time_header()}</Vaul.Title>
					<Button variant="ghost" size="icon-sm" onclick={() => (open = false)}>
						<XIcon />
						<span class="sr-only">{m.close()}</span>
					</Button>
				</div>
			</div>

			<div class="flex flex-col gap-4 px-4 pb-[calc(env(safe-area-inset-bottom)+1rem)]">
				<button
					type="button"
					class="flex w-full items-center justify-between gap-3 rounded-lg border bg-background px-3 py-3
						text-left transition-colors hover:bg-primary/5 cursor-pointer"
					onclick={() => (showCalendar = !showCalendar)}
					title={m.time_pick_date()}
					aria-expanded={showCalendar}
				>
					<span class="flex min-w-0 items-center gap-2.5">
						<CalendarIcon class="size-5 shrink-0 opacity-70" />
						<span class="truncate font-mono tabular-nums text-base">{dateLabel}</span>
					</span>
					<ChevronDownIcon
						class="size-4 shrink-0 opacity-50 transition-transform {showCalendar
							? 'rotate-180'
							: ''}"
					/>
				</button>

				{#if showCalendar}
					<div class="self-center overflow-hidden rounded-md border bg-background">
						<Calendar
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
									focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
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

				<div class="flex items-center justify-between">
					<span class="text-sm text-muted-foreground">{m.time_speed_label()}</span>
					<span class="text-sm tabular-nums">{activeScale.label()}</span>
				</div>

				<div class="-mx-4 overflow-x-auto">
					<div class="flex items-center gap-2 px-4 pb-1">
						{#each TIME_SCALES as { label, value } (value)}
							<button
								type="button"
								class="inline-flex items-center justify-center h-9 px-3 rounded-full whitespace-nowrap text-sm transition-colors cursor-pointer
									{Math.abs(clock.timeScale) === value
									? 'bg-primary text-primary-foreground'
									: 'bg-primary/10 hover:bg-primary/20 text-primary'}"
								onclick={() => clock.setTimeScale(value)}
							>
								{label()}
							</button>
						{/each}
					</div>
				</div>
			</div>
		</Vaul.Content>
	</Vaul.Portal>
</Vaul.Root>
