import { describe, it, expect, vi } from 'vitest';
import { compositionSegments, formatFormula } from './atmosphere-species';
import { formatPressure, formatEarthRatio } from '$lib/format/pressure';

describe('compositionSegments', () => {
	it('ranks by share and folds the tail into trace', () => {
		const segments = compositionSegments([
			{ formula: 'Ar', share: 0.0093 },
			{ formula: 'N2', share: 0.78 },
			{ formula: 'O2', share: 0.21 },
			{ formula: 'CO2', share: 0.004 }
		]);
		expect(segments.map((s) => s.key)).toEqual(['N2', 'O2', 'Ar', '__trace__']);
		expect(segments.at(-1)?.share).toBeCloseTo(0.004);
	});

	// Isotopes are the only formulas whose variable name is not just the
	// lowercased formula, so they are the only naming case worth asserting.
	it('keeps the hyphen when an isotope names its variable', () => {
		const segments = compositionSegments([
			{ formula: 'He-4', share: 0.7 },
			{ formula: 'Ne-20', share: 0.3 }
		]);
		expect(segments.map((s) => s.color)).toEqual(['var(--gas-he-4)', 'var(--gas-ne-20)']);
	});

	it('falls back visibly for a species the palette has never seen', () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		const segments = compositionSegments([
			{ formula: 'N2', share: 0.6 },
			{ formula: 'PH3', share: 0.4 }
		]);
		expect(segments[1].color).toBe('var(--muted-foreground)');
		expect(warn).toHaveBeenCalled();
		warn.mockRestore();
	});

	it('carries the upper-limit flag through', () => {
		const segments = compositionSegments([
			{ formula: 'He', share: 0.66, limit: true },
			{ formula: 'Mg', share: 0.34 }
		]);
		expect(segments[0].limit).toBe(true);
		expect(segments[1].limit).toBe(false);
	});

	it('drops a trace remainder too small to see', () => {
		const segments = compositionSegments([
			{ formula: 'N2', share: 0.9999 },
			{ formula: 'CH4', share: 0.0001 }
		]);
		expect(segments.map((s) => s.key)).toEqual(['N2']);
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
	it('reads as a multiple above Earth and a percentage below', () => {
		expect(formatEarthRatio(9.2e6)).toContain('90.7×');
		expect(formatEarthRatio(636)).toContain('0.63%');
		expect(formatEarthRatio(5e-10)).toContain('4.9×10⁻¹³%');
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
