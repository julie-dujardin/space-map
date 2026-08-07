import { describe, it, expect, vi } from 'vitest';
import { speciesEntries, formatFormula } from './atmosphere-species';
import { formatPressure, formatEarthRatio, EARTH_SEA_LEVEL_PA } from '$lib/format/pressure';

describe('speciesEntries', () => {
	// Isotopes are the only formulas whose variable name is not just the
	// lowercased formula, so they are the only naming case worth asserting.
	it('keeps the hyphen when an isotope names its variable', () => {
		const entries = speciesEntries([
			{ formula: 'He-4', share: 0.7 },
			{ formula: 'Ne-20', share: 0.3 }
		]);
		expect(entries.map((e) => e.color)).toEqual(['var(--gas-he-4)', 'var(--gas-ne-20)']);
	});

	it('falls back visibly for a species the palette has never seen', () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		const entries = speciesEntries([
			{ formula: 'N2', share: 0.6 },
			{ formula: 'PH3', share: 0.4 }
		]);
		expect(entries[1].color).toBe('var(--muted-foreground)');
		expect(warn).toHaveBeenCalled();
		warn.mockRestore();
	});

	it('carries the upper-limit flag through', () => {
		const entries = speciesEntries([
			{ formula: 'He', share: 0.66, limit: true },
			{ formula: 'Mg', share: 0.34 }
		]);
		expect(entries[0].limit).toBe(true);
		expect(entries[1].limit).toBe(false);
	});
});

describe('formatFormula', () => {
	it('subscripts digits and lifts isotope mass numbers', () => {
		expect(formatFormula('CO2')).toBe('CO₂');
		expect(formatFormula('C2H6')).toBe('C₂H₆');
		expect(formatFormula('He-4')).toBe('⁴He');
		expect(formatFormula('Na')).toBe('Na');
	});
});

describe('formatEarthRatio', () => {
	/** Strip the isolates the RTL-safe formatter wraps the number in. */
	const plain = (s: string | null) => s?.replace(/[\u2066\u2069]/g, '') ?? null;

	it('reads as a multiple above Earth and a percentage below', () => {
		expect(plain(formatEarthRatio(9.2e6))).toContain('90.7×');
		expect(plain(formatEarthRatio(636))).toContain('0.63%');
		expect(plain(formatEarthRatio(5e-10))).toContain('4.9×10⁻¹³%');
	});

	it('has nothing to tell Earth about itself', () => {
		expect(formatEarthRatio(EARTH_SEA_LEVEL_PA)).toBeNull();
	});
});

describe('formatPressure', () => {
	it('switches unit and notation with magnitude', () => {
		expect(formatPressure(9.2e6)).toBe('92 bar');
		expect(formatPressure(1.014e5)).toBe('1.01 bar');
		expect(formatPressure(636)).toBe('636 Pa');
		expect(formatPressure(1.15)).toBe('1.15 Pa');
		expect(formatPressure(5e-10)).toBe('5×10⁻¹⁰ Pa');
		expect(formatPressure(1.2e-3)).toBe('1.2×10⁻³ Pa');
	});
});
