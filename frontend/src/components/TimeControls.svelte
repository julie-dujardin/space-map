<script lang="ts">
	import PauseIcon from '@lucide/svelte/icons/pause';
	import type { SimClock } from '$lib/scene/clock.svelte';
	import { dateToJD, jdToDate } from '$lib/format/date';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import * as m from '$lib/paraglide/messages.js';
	import * as Popover from '$lib/components/ui/popover';
	import { Calendar } from '$lib/components/ui/calendar';
	import { CalendarDate, type DateValue } from '@internationalized/date';
	import { untrack } from 'svelte';

	interface Props {
		clock: SimClock;
	}

	let { clock }: Props = $props();

	let pickerOpen = $state(false);
	let pickerValue = $state<DateValue | undefined>(undefined);
	let pickerPlaceholder = $state<DateValue | undefined>(undefined);

	function jdToCalendarDate(jd: number): CalendarDate {
		const d = jdToDate(jd);
		return new CalendarDate(d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate());
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
		const cur = jdToDate(clock.jd);
		const next = new Date(
			Date.UTC(
				v.year,
				v.month - 1,
				v.day,
				cur.getUTCHours(),
				cur.getUTCMinutes(),
				cur.getUTCSeconds(),
				cur.getUTCMilliseconds()
			)
		);
		clock.setJD(dateToJD(next));
	}

	const SCALES: { label: string; value: number }[] = [
		{ label: '1×', value: 1 },
		{ label: '1 min/s', value: 60 },
		{ label: '1 h/s', value: 3600 },
		{ label: '1 d/s', value: 86400 },
		{ label: '1 w/s', value: 604800 },
		{ label: '1 mo/s', value: 2_592_000 },
		{ label: '1 y/s', value: 31_557_600 }
	];

	let dateLabel = $derived.by(() => {
		const d = jdToDate(clock.jd);
		return d.toLocaleString(getLocale(), {
			timeZone: 'UTC',
			year: 'numeric',
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
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
			{clock.playing ? 'hover:bg-primary/10' : 'bg-primary text-primary-foreground'}"
		onclick={() => (clock.playing ? clock.pause() : clock.play())}
		aria-label={clock.playing ? m.time_pause() : m.time_play()}
		title={clock.playing ? m.time_pause() : m.time_play()}
	>
		<PauseIcon class="size-4" />
	</button>

	{#each SCALES as { label, value } (value)}
		<button
			type="button"
			class="inline-flex items-center justify-center h-8 px-2 rounded-md transition-colors cursor-pointer
				{clock.timeScale === value ? 'bg-primary text-primary-foreground' : 'hover:bg-primary/10'}"
			onclick={() => clock.setTimeScale(value)}
		>
			{label}
		</button>
	{/each}

	<span class="self-stretch w-px bg-primary/20 mx-1" aria-hidden="true"></span>

	<Popover.Root bind:open={pickerOpen}>
		<Popover.Trigger
			class="inline-flex items-center h-8 px-2 font-mono tabular-nums
				rounded-md hover:bg-primary/10 transition-colors cursor-pointer"
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
			/>
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
