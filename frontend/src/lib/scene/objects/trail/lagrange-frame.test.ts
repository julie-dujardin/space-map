import { describe, expect, it } from 'vitest';
import { earthHeliocentric, lagrangeSampleTransform } from './lagrange-frame';

describe('earthHeliocentric', () => {
	it('puts Earth near perihelion in early January', () => {
		const { r } = earthHeliocentric(2451548.5);
		expect(r).toBeCloseTo(0.9833, 3);
	});

	it('advances ~360° over a year', () => {
		const a = earthHeliocentric(2460000).lon;
		const b = earthHeliocentric(2460365.25).lon;
		expect(((b - a) * 180) / Math.PI).toBeCloseTo(360, 0);
	});
});

describe('lagrangeSampleTransform', () => {
	it('is the identity at the current date', () => {
		const v = new Float64Array([1, 2, 3]);
		lagrangeSampleTransform(2460000)(2460000, v);
		expect([...v]).toEqual([1, 2, 3]);
	});

	it('keeps a point on the Sun–Earth line on that line', () => {
		const jdNow = 2460100;
		const jdThen = jdNow - 91;
		const then = earthHeliocentric(jdThen);
		const now = earthHeliocentric(jdNow);
		// Anti-sunward unit offset at the sample date.
		const v = new Float64Array([Math.cos(then.lon), 0, -Math.sin(then.lon)]);
		lagrangeSampleTransform(jdNow)(jdThen, v);
		expect(v[0]).toBeCloseTo(Math.cos(now.lon), 9);
		expect(v[2]).toBeCloseTo(-Math.sin(now.lon), 9);
	});
});
