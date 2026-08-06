import { describe, it, expect } from 'vitest';
import { foldTrace, type CompositionEntry } from './composition-bar';

function entries(shares: Record<string, number>): CompositionEntry[] {
	return Object.entries(shares).map(([key, share]) => ({
		key,
		label: key,
		name: key,
		share,
		color: 'red'
	}));
}

describe('foldTrace', () => {
	it('ranks by share and folds what is under a percent', () => {
		const { shown, folded, trace } = foldTrace(
			entries({ Ar: 0.0093, N2: 0.78, O2: 0.21, CO2: 0.004 })
		);
		expect(shown.map((e) => e.key)).toEqual(['N2', 'O2']);
		expect(folded.map((e) => e.key)).toEqual(['Ar', 'CO2']);
		expect(trace).toBeCloseTo(0.0133);
	});

	// A bucket standing for one thing is that thing with its name taken off.
	it('keeps a lone minor species rather than bucketing it alone', () => {
		const { shown, folded, trace } = foldTrace(entries({ N2: 0.999, CH4: 0.001 }));
		expect(shown.map((e) => e.key)).toEqual(['N2', 'CH4']);
		expect(folded).toEqual([]);
		expect(trace).toBe(0);
	});

	it('folds the tail once the legend is full, however abundant it is', () => {
		const { shown, folded } = foldTrace(
			entries({ a: 0.3, b: 0.2, c: 0.15, d: 0.14, e: 0.12, f: 0.05, g: 0.03, h: 0.01 })
		);
		expect(shown.map((e) => e.key)).toEqual(['a', 'b', 'c', 'd', 'e', 'f']);
		expect(folded.map((e) => e.key)).toEqual(['g', 'h']);
	});
});
