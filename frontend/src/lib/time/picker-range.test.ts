import { describe, expect, it } from 'vitest';
import { CalendarDate } from '@internationalized/date';
import type { Metadata } from '$lib/fetch/metadata';
import { dateToJD, utcToTdb } from './jd';
import { daysIn, pickerRangeOf } from './picker-range.svelte';

/** A local wall-clock instant as a UTC JD. */
const local = (y: number, mo: number, d: number, h = 0, mi = 0) =>
	dateToJD(new Date(y, mo - 1, d, h, mi));

describe('daysIn', () => {
	it('starts on the first day whose midnight is covered', () => {
		expect(daysIn(local(1600, 1, 1), local(2600, 1, 1)).min).toEqual(new CalendarDate(1600, 1, 1));
		expect(daysIn(local(1599, 12, 31, 23, 58), local(2600, 1, 1)).min).toEqual(
			new CalendarDate(1600, 1, 1)
		);
		expect(daysIn(local(1600, 1, 1, 0, 2), local(2600, 1, 1)).min).toEqual(
			new CalendarDate(1600, 1, 2)
		);
	});

	it('ends on the last day whose midnight is covered', () => {
		expect(daysIn(local(1600, 1, 1), local(2599, 12, 31, 23, 58)).max).toEqual(
			new CalendarDate(2599, 12, 31)
		);
	});
});

describe('pickerRangeOf', () => {
	it("spans the planets' ephemeris", () => {
		const start = utcToTdb(local(1600, 1, 1, 12));
		const end = utcToTdb(local(2600, 1, 1, 12));
		const meta = {
			position: {
				zones: {
					major: {
						zooms: {
							'0': {
								shape: 'chunked',
								chunks: 1,
								chunk_days: 1,
								start_jd: start,
								end_jd: end,
								bodies: {}
							}
						}
					}
				}
			}
		} as unknown as Metadata;
		expect(pickerRangeOf(meta)).toEqual({
			min: new CalendarDate(1600, 1, 2),
			max: new CalendarDate(2600, 1, 1)
		});
	});
});
