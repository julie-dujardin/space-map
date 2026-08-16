import { CalendarDate, type DateValue } from '@internationalized/date';
import type { SimClock } from '$lib/scene/state/clock.svelte';
import { dateToJD, jdToDate } from '$lib/format/date';

export function jdToCalendarDate(jd: number): CalendarDate {
	const d = jdToDate(jd);
	return new CalendarDate(d.getFullYear(), d.getMonth() + 1, d.getDate());
}

export function applyDateToClock(clock: SimClock, v: DateValue | undefined): void {
	if (!v) return;
	const next = jdToDate(clock.jd);
	next.setFullYear(v.year, v.month - 1, v.day);
	clock.jumpTo(dateToJD(next));
}

export function applyTimeToClock(clock: SimClock, e: Event): void {
	const match = (e.currentTarget as HTMLInputElement).value.match(/^(\d{2}):(\d{2})$/);
	if (!match) return;
	const next = jdToDate(clock.jd);
	next.setHours(Number(match[1]), Number(match[2]), 0, 0);
	clock.jumpTo(dateToJD(next));
}

/** "HH:MM" — local time portion of the clock's current jd. */
export function clockTimeValue(jd: number): string {
	const d = jdToDate(jd);
	return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}
