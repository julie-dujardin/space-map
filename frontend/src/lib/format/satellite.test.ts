import { describe, expect, it } from 'vitest';
import { formatCountry } from './satellite';

describe('formatCountry', () => {
	it('keeps a dissolved state out of its successor', () => {
		// Intl resolves SU to Russia and CS to Serbia, which is the opposite of
		// what a launch registered to either of them means.
		expect(formatCountry('SU')).toBe('Soviet Union');
		expect(formatCountry('CS')).toBe('Czechoslovakia');
	});

	it('still answers for a current country', () => {
		expect(formatCountry('JP')).toBe('Japan');
	});
});
