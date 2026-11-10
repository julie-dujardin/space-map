import { CalendarDate } from '@internationalized/date';
import { chebyshevZoneParams, fetchMetadata, type Metadata } from '$lib/fetch/metadata';
import { jdToDate, tdbToUtc } from '$lib/time/jd';

interface Range {
	min: CalendarDate;
	max: CalendarDate;
}

function localDay(date: Date): CalendarDate {
	return new CalendarDate(date.getFullYear(), date.getMonth() + 1, date.getDate());
}

/** The local days whose midnight lies in `[start, end]` (UTC JD). */
export function daysIn(start: number, end: number): Range {
	const first = jdToDate(start);
	const firstDay = localDay(first);
	const midnight = new Date(first);
	midnight.setHours(0, 0, 0, 0);
	return {
		min: midnight.getTime() < first.getTime() ? firstDay.add({ days: 1 }) : firstDay,
		max: localDay(jdToDate(end))
	};
}

/** The span of the planets' ephemeris, the `major` zone: the dates the map has
 *  a Solar System at. */
export function pickerRangeOf(meta: Metadata): Range | null {
	const major = chebyshevZoneParams(meta).get('major');
	return major ? daysIn(tdbToUtc(major.start_jd), tdbToUtc(major.end_jd)) : null;
}

let range = $state<Range | null>(null);
let asked = false;

/** The pickers' bounds. Null until the manifest is read: unbounded then. */
export function pickerRange(): Range | null {
	return range;
}

/** Read the bounds from the manifest, once. Call from the browser only. */
export function loadPickerRange(): void {
	if (asked) return;
	asked = true;
	fetchMetadata().then(
		(meta) => (range = pickerRangeOf(meta)),
		() => (asked = false)
	);
}
