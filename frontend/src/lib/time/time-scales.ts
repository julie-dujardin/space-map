import { CalendarDate } from '@internationalized/date';
import * as m from '$lib/paraglide/messages.js';

export interface TimeScale {
	label: () => string;
	value: number;
}

export const TIME_SCALES: readonly TimeScale[] = [
	{ label: () => m.time_scale_realtime(), value: 1 },
	{ label: () => m.time_scale_min_per_sec(), value: 60 },
	{ label: () => m.time_scale_hour_per_sec(), value: 3600 },
	{ label: () => m.time_scale_day_per_sec(), value: 86400 },
	{ label: () => m.time_scale_week_per_sec(), value: 604800 },
	{ label: () => m.time_scale_month_per_sec(), value: 2_592_000 },
	{ label: () => m.time_scale_year_per_sec(), value: 31_557_600 }
];

export const TIME_DATE_OPTS: Intl.DateTimeFormatOptions = {
	year: 'numeric',
	month: 'short',
	day: 'numeric',
	hour: '2-digit',
	minute: '2-digit'
};

// Range with the best ephemeris/orbital-data coverage; the date picker is
// clamped to it (the clock itself can still drift outside via fast playback).
export const PICKER_MIN_DATE = new CalendarDate(1950, 1, 1);
export const PICKER_MAX_DATE = new CalendarDate(2050, 12, 31);
