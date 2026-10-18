import { describe, expect, it } from 'vitest';
import { formatCountry, probeState } from './satellite';

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

describe('probeState', () => {
	it('takes the curated record over a stale catalogue code', () => {
		// MarCO-A: SATCAT still files it operational, years after its last signal.
		expect(probeState({ where: 'heliocentric', alive: false }, 'operational')).toBe('ended');
		expect(probeState({ where: 'landed', alive: true }, 'decayed')).toBe('operating');
	});

	it('names a failure before the place it came to rest', () => {
		expect(probeState({ where: 'landed', alive: false, lost: true }, 'decayed')).toBe('lost');
		expect(probeState({ where: 'landed', alive: false }, 'decayed')).toBe('landed');
	});

	it('keeps a partial craft partial', () => {
		expect(probeState({ where: 'heliocentric', alive: true }, 'partial')).toBe('partial');
	});

	it('falls back to the catalogue where the record does not know', () => {
		expect(probeState(undefined, 'extended_mission')).toBe('operating');
		expect(probeState({ where: 'heliocentric' }, 'nonoperational')).toBe('ended');
		expect(probeState({ where: 'landed' }, 'decayed')).toBe('landed');
	});

	it('has no word where neither knows', () => {
		expect(probeState({ where: 'heliocentric' }, undefined)).toBeNull();
		expect(probeState(undefined, 'unknown')).toBeNull();
	});
});
