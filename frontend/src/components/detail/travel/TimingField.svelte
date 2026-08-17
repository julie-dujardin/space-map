<!--
  When the trip goes, as one control: the closed field states the answer in
  full — "Leave now", "Depart Dec 15, 2026", "Arrive by Dec 15, 2026" — and
  opens on the three modes with a calendar under the two that need one.

  One control rather than a mode beside a date pill: the mode named the date's
  meaning and the pill repeated it, and a date that only some modes carry made
  the line change width as the mode changed.
-->
<script lang="ts">
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import { type DateValue } from '@internationalized/date';
	import * as Popover from '$lib/components/ui/popover';
	import { Calendar } from '$lib/components/ui/calendar';
	import { PICKER_MAX_DATE, PICKER_MIN_DATE } from '$lib/scene/time-scales';
	import { dateToJD, formatJulianDate, jdToDate } from '$lib/format/date';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import * as m from '$lib/paraglide/messages.js';
	import type { TimeMode } from '$lib/travel/trip';
	import { jdToCalendarDate } from '../../time/clock-pickers';

	interface Props {
		mode: TimeMode;
		/** The chosen date. The caller seeds it, so the calendar is never empty. */
		jd: number;
		onModeChange: (mode: TimeMode) => void;
		onDateChange: (jd: number) => void;
	}
	let { mode, jd, onModeChange, onDateChange }: Props = $props();

	let open = $state(false);
	let value = $derived<DateValue | undefined>(jdToCalendarDate(jd));
	let placeholder = $state<DateValue | undefined>(undefined);

	const TABS: { value: TimeMode; label: string }[] = [
		{ value: 'now', label: m.travel_time_now() },
		{ value: 'depart', label: m.travel_time_depart() },
		{ value: 'arrive', label: m.travel_time_arrive() }
	];

	// The whole sentence, so the trip's timing reads off the closed field.
	let label = $derived(
		mode === 'now'
			? m.travel_time_now()
			: mode === 'depart'
				? m.travel_time_depart_date({ date: formatJulianDate(jd) })
				: m.travel_time_arrive_date({ date: formatJulianDate(jd) })
	);

	function chooseMode(next: TimeMode) {
		onModeChange(next);
		// "Now" has nothing left to ask; the other two have a date to pick.
		if (next === 'now') open = false;
	}

	function pick(next: DateValue | undefined) {
		if (!next) return;
		// Keep the time of day the trip already carries; only the date is picked.
		const d = jdToDate(jd);
		d.setFullYear(next.year, next.month - 1, next.day);
		onDateChange(dateToJD(d));
		open = false;
	}
</script>

<Popover.Root bind:open>
	<!-- Muted, like the braking choice at the other end of the line: both are terms
	     of the trip that state themselves and stay out of the trajectories' way. -->
	<Popover.Trigger
		class="text-muted-foreground hover:text-foreground data-[state=open]:text-foreground flex shrink-0 items-center gap-1 text-xs transition-colors"
		aria-label={m.travel_when()}
	>
		{label}
		<ChevronDownIcon
			class="text-muted-foreground size-3.5 shrink-0 transition-transform {open
				? 'rotate-180'
				: ''}"
			aria-hidden="true"
		/>
	</Popover.Trigger>
	<Popover.Content class="w-auto p-2" align="start" sideOffset={6}>
		<div
			class="bg-muted/40 flex rounded-md p-0.5 text-xs"
			role="tablist"
			aria-label={m.travel_when()}
		>
			{#each TABS as tab (tab.value)}
				{@const active = tab.value === mode}
				<button
					type="button"
					role="tab"
					aria-selected={active}
					onclick={() => chooseMode(tab.value)}
					class="flex-1 rounded px-2 py-1 whitespace-nowrap transition-colors {active
						? 'bg-background text-foreground shadow-sm'
						: 'text-muted-foreground hover:text-foreground'}"
				>
					{tab.label}
				</button>
			{/each}
		</div>

		{#if mode !== 'now'}
			<!-- The columns share the width rather than each taking a fixed cell: the
			     popover is as wide as the tab row above, which is wider than seven
			     cells, and the slack would otherwise pool at one edge. Each day keeps
			     its own size and centres in the column it was given. -->
			<Calendar
				class="w-full px-0 pt-2 pb-0 [&_td]:w-[calc(100%/7)] [&_th]:w-[calc(100%/7)] [&_[data-bits-day]]:mx-auto"
				type="single"
				{value}
				bind:placeholder
				onValueChange={pick}
				captionLayout="dropdown"
				locale={getLocale()}
				minValue={PICKER_MIN_DATE}
				maxValue={PICKER_MAX_DATE}
			/>
		{/if}
	</Popover.Content>
</Popover.Root>
