import { describe, expect, it } from 'vitest';
import { DENSITY_LADDER, densityComparison, nearestRung } from './density';

const ISOLATES = new RegExp('[\\u2066-\\u2069]', 'g');
const compare = (gcm3: number | [number, number]) => densityComparison(gcm3)?.replace(ISOLATES, '');

describe('the density ladder', () => {
	it('takes the rung nearest in log space', () => {
		const rung = (gcm3: number) => DENSITY_LADDER.indexOf(nearestRung(gcm3));
		// Each boundary is the geometric mean of the two rungs beside it.
		for (let i = 0; i + 1 < DENSITY_LADDER.length; i++) {
			const edge = Math.sqrt(DENSITY_LADDER[i].gcm3 * DENSITY_LADDER[i + 1].gcm3);
			expect(rung(edge * 0.999)).toBe(i);
			expect(rung(edge * 1.001)).toBe(i + 1);
		}
		expect(rung(1e-9)).toBe(0);
		expect(rung(1e18)).toBe(DENSITY_LADDER.length - 1);
	});

	it('reads as a multiple or a share of that rung', () => {
		expect(compare(1.41)).toBe('1.41× water');
		expect(compare(0.69)).toBe('69% of water');
		expect(compare(9.8e-5)).toBe('8% of sea-level air');
		expect(compare(5.51)).toBe('70% of iron');
		expect(compare(3.34)).toBe('1.24× crustal rock');
		expect(compare(2.7e6)).toBe('140,000× tungsten');
		expect(compare(4.6e14)).toBe('2× an atomic nucleus');
	});

	it('says nothing on a rung', () => {
		expect(compare(1)).toBeUndefined();
	});

	it('compares both ends of a span', () => {
		expect(compare([150, 160])).toBe('7.79–8.31× tungsten');
		expect(compare([0.5, 0.6])).toBe('50%–60% of water');
		expect(compare([0.9, 1.1])).toBeUndefined();
	});
});
