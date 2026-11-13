import type { CalendarDate, DateValue } from '@internationalized/date';
import type { SimClock } from '$lib/scene/state/clock.svelte';
import { formatDecimalTime, type CalendarId } from '$lib/time/calendars';
import { extendedYear, fromPickerDate, toPickerDate } from '$lib/time/calendars/picker';
import { dateToJD, jdToDate } from '$lib/time/jd';

/** The local day of the clock's `jd`, in the picker's calendar. */
export function jdToCalendarDate(jd: number, calendar: CalendarId = 'gregory'): CalendarDate {
	const d = jdToDate(jd);
	return toPickerDate(d.getFullYear(), d.getMonth() + 1, d.getDate(), calendar);
}

export function applyDateToClock(clock: SimClock, v: DateValue | undefined): void {
	if (!v) return;
	const { year, month, day } = fromPickerDate(v);
	const next = jdToDate(clock.jd);
	next.setFullYear(year, month - 1, day);
	clock.jumpTo(dateToJD(next));
}

export interface PickerBounds {
	min: CalendarDate;
	max: CalendarDate;
	/** Every year between, counted through the calendar's epoch. */
	years: number[];
}

/** The picker's Gregorian bounds, in the calendar it lays out. */
export function pickerBounds(
	range: { min: CalendarDate; max: CalendarDate } | null,
	calendar: CalendarId
): PickerBounds | undefined {
	if (!range) return undefined;
	const min = toPickerDate(...gregorianFields(range.min), calendar);
	const max = toPickerDate(...gregorianFields(range.max), calendar);
	const first = extendedYear(min);
	const last = extendedYear(max);
	return { min, max, years: Array.from({ length: last - first + 1 }, (_, i) => first + i) };
}

function gregorianFields(date: CalendarDate): [number, number, number] {
	const { year, month, day } = fromPickerDate(date);
	return [year, month, day];
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

/** "h:mm" in decimal time: the local day's ten hours of a hundred minutes. */
export function decimalTimeValue(jd: number): string {
	return formatDecimalTime(jdToDate(jd));
}

/**
 * A decimal time typed as "7:83", "7h83" or a bare "7", read as hours of the
 * local day the clock is on. Null when it is not one: ten hours, a hundred
 * minutes.
 */
export function parseDecimalTime(text: string): number | null {
	const match = text.trim().match(/^(\d)(?:\s*[:h.,]\s*(\d{1,2}))?$/i);
	if (!match) return null;
	const minutes = match[2] === undefined ? 0 : Number(match[2].padEnd(2, '0'));
	return (Number(match[1]) * 100 + minutes) / 1000;
}

/** Move the clock to `fraction` of its local day, keeping the day. */
export function applyDayFractionToClock(clock: SimClock, fraction: number): void {
	const start = jdToDate(clock.jd);
	start.setHours(0, 0, 0, 0);
	const end = new Date(start);
	end.setDate(end.getDate() + 1);
	clock.jumpTo(dateToJD(new Date(start.getTime() + (end.getTime() - start.getTime()) * fraction)));
}
