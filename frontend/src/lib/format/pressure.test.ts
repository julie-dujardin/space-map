import { describe, it, expect } from 'vitest';

// No runtime mock: the unit symbols come out of paraglide, and stubbing the
// runtime cuts the messages off from their locale.
import { formatPressure, formatPressureSpan } from './pressure';

describe('formatPressure', () => {
	it.each([
		{ pa: 9.2e6, expected: '92 bar' },
		{ pa: 1.014e5, expected: '1.01 bar' },
		{ pa: 636, expected: '636 Pa' },
		{ pa: 0.3734, expected: '0.373 Pa' },
		{ pa: 8.213e-8, expected: '8.2×10⁻⁸ Pa' }
	])('$pa Pa → $expected', ({ pa, expected }) => {
		expect(formatPressure(pa)).toBe(expected);
	});

	it('has nothing to say about a vacuum', () => {
		expect(formatPressure(0)).toBe('');
	});
});

describe('formatPressureSpan', () => {
	it('says the unit once where both ends are in it', () => {
		// Closed up, the way every other span in the app sets one: the wide
		// separator is what the two ends take when each carries its own unit.
		expect(formatPressureSpan(1.014e5, 22632)).toBe('1.01–0.226 bar');
	});

	it('repeats it across the bar/pascal boundary', () => {
		// Earth's stratosphere. "0.226 – 66.9 Pa" would be off by four orders of
		// magnitude.
		expect(formatPressureSpan(22632, 66.939)).toBe('0.226 bar – 66.9 Pa');
	});

	it('keeps scientific notation at the thin end', () => {
		expect(formatPressureSpan(0.3734, 8.213e-8)).toBe('0.373–8.2×10⁻⁸ Pa');
	});

	it('states one number where the ends round together', () => {
		expect(formatPressureSpan(1e4, 1.0004e4)).toBe('0.1 bar');
	});

	it('falls back to the end it has where the other is no reading', () => {
		expect(formatPressureSpan(636, 0)).toBe('636 Pa');
	});
});
