import { describe, it, expect } from 'vitest';
import { RANGE_DEFS, rangeDef, toPos, fromPos } from './ranges';

describe('range scales', () => {
	it('pins the domain ends to 0 and 1', () => {
		for (const def of RANGE_DEFS) {
			expect(toPos(def, def.lo)).toBeCloseTo(0, 6);
			expect(toPos(def, def.hi)).toBeCloseTo(1, 6);
		}
	});

	it('clamps out-of-domain values', () => {
		const d = rangeDef('diameter');
		expect(toPos(d, d.lo / 10)).toBe(0);
		expect(toPos(d, d.hi * 10)).toBe(1);
	});

	it('is monotonic in position', () => {
		for (const def of RANGE_DEFS) {
			let prev = -Infinity;
			for (let p = 0; p <= 1.0001; p += 0.1) {
				const v = fromPos(def, p);
				expect(v).toBeGreaterThanOrEqual(prev);
				prev = v;
			}
		}
	});

	it('round-trips a snapped value through pos', () => {
		const d = rangeDef('diameter');
		const v = fromPos(d, 0.5); // log midpoint, 2 sig figs
		expect(fromPos(d, toPos(d, v))).toBe(v);
	});

	it('gives recent years more of the date track (reverse-log)', () => {
		const d = rangeDef('inception');
		// The last 26 years (2000→2026) occupy more than half the slider.
		expect(toPos(d, 2000)).toBeLessThan(0.5);
		expect(toPos(d, 2000)).toBeGreaterThan(0.1);
		// ...whereas a linear scale would place 2000 at ~0.92 over [1700, 2026].
	});
});
