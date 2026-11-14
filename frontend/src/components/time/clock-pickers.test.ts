import { describe, expect, it } from 'vitest';

import { parseDecimalTime } from './clock-pickers';

describe('parseDecimalTime', () => {
	it.each([
		['5:00', 0.5],
		['7:83', 0.783],
		['7h83', 0.783],
		['0:05', 0.005],
		['9:99', 0.999],
		['3', 0.3],
		// A lone figure after the colon is tenths of the hour, as on the dial.
		['2:5', 0.25]
	])('reads “%s” as %f of the day', (text, fraction) => {
		expect(parseDecimalTime(text)).toBeCloseTo(fraction, 10);
	});

	it.each(['10:00', '7:830', '19:30', 'noon', ''])('refuses “%s”', (text) => {
		expect(parseDecimalTime(text)).toBeNull();
	});
});
