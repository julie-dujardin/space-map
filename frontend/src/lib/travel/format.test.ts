import { describe, it, expect } from 'vitest';
import {
	formatAcceleration,
	formatSpeed,
	formatTripTime,
	lightPercent,
	tripDuration
} from './format';

/** Days per month the formatter rounds against. */
const MONTH = 30.44;
const HOUR = 1 / 24;
const MINUTE = 1 / 1440;

// Only the unit choice and the carries are ours; spelling them is Intl's job.
describe('tripDuration', () => {
	it('picks the two largest units that carry anything', () => {
		expect(tripDuration(25 * MINUTE)).toEqual({ hours: 0, minutes: 25 });
		expect(tripDuration(6 * HOUR + 20 * MINUTE)).toEqual({ hours: 6, minutes: 20 });
		expect(tripDuration(3.5)).toEqual({ days: 3, hours: 12 });
		expect(tripDuration(MONTH * 6 + 20)).toEqual({ months: 6, days: 20 });
		expect(tripDuration(MONTH * 45 + 25)).toEqual({ years: 3, months: 9 });
	});

	// Rounding the smaller unit can reach a full larger one; "3 mo 30 d" is not a
	// duration anyone writes.
	it('carries a rounded remainder up the ladder', () => {
		expect(tripDuration(59.7 * MINUTE)).toEqual({ hours: 1 });
		expect(tripDuration(23.999 * HOUR)).toEqual({ days: 1 });
		expect(tripDuration(MONTH * 3 + 30.2)).toEqual({ months: 4 });
		expect(tripDuration(MONTH * 11 + 30.2)).toEqual({ years: 1 });
	});
});

describe('formatAcceleration', () => {
	it('quotes a drive you could stand up in as a fraction of a gravity', () => {
		expect(formatAcceleration(9.80665 / 3)).toBe('0.33 g');
		expect(formatAcceleration(9.80665 * 1.5)).toBe('1.5 g');
	});

	// A hundredth of a gravity is where the fraction stops saying anything.
	it('drops to m/s² for a drive you would never feel', () => {
		expect(formatAcceleration(0.002)).toBe('0.002 m/s²');
	});

	it('refuses to render an acceleration that is not one', () => {
		expect(formatAcceleration(0)).toBe('—');
		expect(formatAcceleration(NaN)).toBe('—');
	});
});

describe('formatSpeed', () => {
	it('stays in km/s below a hundredth of c', () => {
		expect(formatSpeed(993)).toBe('993.00 km/s');
		expect(lightPercent(993)).toBeNull();
	});

	it('flips to a percentage of c from 1% up', () => {
		expect(formatSpeed(2997.92458)).toBe('1% c');
		expect(formatSpeed(6500)).toBe('2.2% c');
	});

	// Newtonian arithmetic on a fictional drive can pass c; the figure is the
	// model's honest output, so it is shown rather than capped.
	it('does not cap a superluminal figure', () => {
		expect(formatSpeed(449688.687)).toBe('150% c');
	});

	it('refuses to render a nonsense speed', () => {
		expect(formatSpeed(NaN)).toBe('—');
	});
});

describe('formatTripTime', () => {
	// Every zero field is dropped, so nothing at all would format to nothing.
	it('names a unit for a trip of no time', () => {
		expect(formatTripTime(0)).toBe('0m');
	});

	it('refuses to render a nonsense duration', () => {
		expect(formatTripTime(NaN)).toBe('—');
		expect(formatTripTime(-1)).toBe('—');
	});
});
