import { describe, expect, it } from 'vitest';
import { planckianRgb, starColours, teffFromBpRp } from './colour';

describe('star colour', () => {
	it('reads the dwarf sequence and clamps at its ends', () => {
		expect(teffFromBpRp(0.823)).toBe(5770);
		expect(teffFromBpRp(0.8275)).toBeCloseTo(5745, 6);
		expect(teffFromBpRp(-1)).toBe(10700);
		expect(teffFromBpRp(9)).toBe(2420);
	});

	it('falls in temperature as the colour reddens', () => {
		let last = Infinity;
		for (let c = -0.2; c < 5.2; c += 0.05) {
			const t = teffFromBpRp(c);
			expect(t).toBeLessThanOrEqual(last);
			last = t;
		}
	});

	it('gives a hot star blue, a cool one red, and the Sun near white', () => {
		const rgb: [number, number, number] = [0, 0, 0];
		planckianRgb(10000, rgb);
		expect(rgb[2]).toBe(1);
		expect(rgb[0]).toBeLessThan(0.9);
		planckianRgb(3000, rgb);
		expect(rgb[0]).toBe(1);
		expect(rgb[2]).toBeLessThan(0.4);
		planckianRgb(5770, rgb);
		expect(rgb[0]).toBe(1);
		expect(rgb[2]).toBeGreaterThan(0.75);
	});

	it('writes three bytes per star, white for no colour', () => {
		const out = starColours(new Float32Array([NaN, 0.823, 3.8]), new Uint8Array(9));
		expect([...out.subarray(0, 3)]).toEqual([255, 255, 255]);
		expect(out[3]).toBe(255);
		expect(out[8]).toBeLessThan(out[6]);
	});
});
