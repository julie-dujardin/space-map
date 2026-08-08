<!--
  The date behind "depart at" / "arrive by".

  Without it those two modes are indistinguishable from "leave now" — the search
  window falls back to the same span — so the field appears with the mode and
  starts on today rather than empty.
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

<div class="flex items-center justify-between gap-2">
	<span class="text-muted-foreground shrink-0 text-xs">{label}</span>
	<Popover.Root bind:open>
		<Popover.Trigger
			class="border-border/60 bg-muted/40 hover:bg-muted flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs tabular-nums"
		>
			<CalendarIcon class="text-muted-foreground size-3.5 shrink-0" />
			{formatJulianDate(jd)}
		</Popover.Trigger>
		<Popover.Content class="w-auto p-0" align="end" sideOffset={6}>
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
</div>
