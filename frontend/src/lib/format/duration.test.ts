import { describe, it, expect } from 'vitest';
import { durationUnits, formatDurationNarrow } from './duration';

/** Days per month the formatter rounds against. */
const MONTH = 30.44;
const HOUR = 1 / 24;
const MINUTE = 1 / 1440;
const SECOND = 1 / 86_400;

// Only the unit choice and the carries are ours; spelling them is Intl's job.
describe('durationUnits', () => {
	it('picks the two largest units that carry anything', () => {
		expect(durationUnits(40 * SECOND)).toEqual({ minutes: 0, seconds: 40 });
		expect(durationUnits(25.5 * MINUTE)).toEqual({ minutes: 25, seconds: 30 });
		expect(durationUnits(6 * HOUR + 20 * MINUTE)).toEqual({ hours: 6, minutes: 20 });
		expect(durationUnits(3.5)).toEqual({ days: 3, hours: 12 });
		expect(durationUnits(MONTH * 6 + 20)).toEqual({ months: 6, days: 20 });
		expect(durationUnits(MONTH * 45 + 25)).toEqual({ years: 3, months: 9 });
	});

	// Rounding the smaller unit can reach a full larger one; "3 mo 30 d" is not a
	// duration anyone writes.
	it('carries a rounded remainder up the ladder', () => {
		expect(durationUnits(59.995 * MINUTE)).toEqual({ hours: 1 });
		expect(durationUnits(23.999 * HOUR)).toEqual({ days: 1 });
		expect(durationUnits(MONTH * 3 + 30.2)).toEqual({ months: 4 });
		expect(durationUnits(MONTH * 11 + 30.2)).toEqual({ years: 1 });
	});
});

describe('formatDurationNarrow', () => {
	it('spells a signal delay down to seconds', () => {
		expect(formatDurationNarrow(83 * SECOND)).toBe('1m 23s');
		expect(formatDurationNarrow(779_866 * SECOND)).toBe('9d 1h');
	});

	// Rounding 59m 60s up lands on a full hour, not on "60m".
	it('carries a rounded minute into the hour', () => {
		expect(formatDurationNarrow(3599.7 * SECOND)).toBe('1h');
	});

	// Every zero field is dropped, so nothing at all would format to nothing.
	it('names a unit for no time at all', () => {
		expect(formatDurationNarrow(0)).toBe('0s');
	});

	it('refuses to render a nonsense duration', () => {
		expect(formatDurationNarrow(NaN)).toBe('—');
		expect(formatDurationNarrow(-1)).toBe('—');
	});
});
