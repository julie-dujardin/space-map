import { describe, expect, it } from 'vitest';
import { metallicityComparison } from './metallicity';

const ISOLATES = new RegExp('[\\u2066-\\u2069]', 'g');
const compare = (dex: number, quantity: 'mh' | 'feh') =>
	metallicityComparison(dex, quantity).replace(ISOLATES, '');

describe('a metallicity against the Sun', () => {
	it('reads as a multiple either way', () => {
		expect(compare(0.2, 'mh')).toBe('1.6× more heavy elements than the Sun');
		expect(compare(-1.05, 'mh')).toBe('11× less heavy elements than the Sun');
	});

	it('says iron for [Fe/H]', () => {
		expect(compare(-0.3, 'feh')).toBe('2× less iron than the Sun');
		expect(compare(0.5, 'feh')).toBe('3.2× more iron than the Sun');
	});

	it('matches the Sun within rounding of 1', () => {
		expect(compare(0, 'feh')).toBe('As rich in iron as the Sun');
		// 10^0.02 is 1.047, which rounds to 1.
		expect(compare(0.02, 'mh')).toBe('As rich in heavy elements as the Sun');
		expect(compare(-0.02, 'mh')).toBe('As rich in heavy elements as the Sun');
		expect(compare(0.03, 'mh')).toBe('1.1× more heavy elements than the Sun');
		expect(compare(-0.03, 'feh')).toBe('1.1× less iron than the Sun');
	});
});
