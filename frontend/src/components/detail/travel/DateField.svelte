<!--
  The date behind "depart at" / "arrive by" — without it those modes are
  indistinguishable from "leave now", so the field starts on today rather
  than empty.

  A pill on the timing line, next to the mode that asked for it: the mode
  already names what the date means, so it carries no visible label.
-->
<script lang="ts">
	import CalendarIcon from '@lucide/svelte/icons/calendar';
	import { type DateValue } from '@internationalized/date';
	import * as Popover from '$lib/components/ui/popover';
	import { Calendar } from '$lib/components/ui/calendar';
	import { PICKER_MAX_DATE, PICKER_MIN_DATE } from '$lib/scene/time-scales';
	import { dateToJD, formatJulianDate, jdToDate } from '$lib/format/date';
	import { jdToCalendarDate } from '../../time/clock-pickers';
	import { getLocale } from '$lib/paraglide/runtime.js';

	interface Props {
		label: string;
		/** The chosen date; the caller seeds it so the field is never empty. */
		jd: number;
		onChange: (jd: number) => void;
	}
	let { label, jd, onChange }: Props = $props();

	let open = $state(false);
	let value = $derived<DateValue | undefined>(jdToCalendarDate(jd));
	let placeholder = $state<DateValue | undefined>(undefined);

	function pick(next: DateValue | undefined) {
		if (!next) return;
		// Keep the time of day the trip already carries; only the date is picked.
		const d = jdToDate(jd);
		d.setFullYear(next.year, next.month - 1, next.day);
		onChange(dateToJD(d));
		open = false;
	}
</script>

<Popover.Root bind:open>
	<Popover.Trigger
		class="border-border/60 bg-muted/40 hover:bg-muted flex shrink-0 items-center gap-1.5 rounded-md border px-2 py-1 text-xs tabular-nums transition-colors"
	>
		<!-- A bare date announces nothing about which one, and the mode beside it is
		     a separate control, so the label is the accessible name here. -->
		<span class="sr-only">{label}</span>
		<CalendarIcon class="text-muted-foreground size-3.5 shrink-0" aria-hidden="true" />
		{formatJulianDate(jd)}
	</Popover.Trigger>
	<Popover.Content class="w-auto p-0" align="start" sideOffset={6}>
		<Calendar
			type="single"
			{value}
			bind:placeholder
			onValueChange={pick}
			captionLayout="dropdown"
			locale={getLocale()}
			minValue={PICKER_MIN_DATE}
			maxValue={PICKER_MAX_DATE}
		/>
	</Popover.Content>
</Popover.Root>
