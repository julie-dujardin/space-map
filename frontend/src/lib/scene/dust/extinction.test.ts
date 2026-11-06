import { describe, expect, it } from 'vitest';
import { starColours } from '$lib/scene/starfield/colour';
import {
	BLUE_END,
	BOUND_MAX,
	BRIGHTEST_M0,
	DUST_COLOUR_GLSL,
	K_G,
	K_RGB,
	decodeBound,
	dustBound,
	dustBounds
} from './extinction';

describe('extinction law', () => {
	it('takes more blue than red, with G between red and green', () => {
		expect(K_RGB[2]).toBeGreaterThan(K_RGB[1]);
		expect(K_RGB[1]).toBeGreaterThan(K_RGB[0]);
		expect(K_G).toBeLessThan(K_RGB[0]);
	});

	it('leaves every colour of the table above the blue end', () => {
		const count = 400;
		const bpRp = Float32Array.from({ length: count }, (_, i) => -1 + (i / count) * 6);
		const bytes = starColours(bpRp, new Uint8Array(3 * count));
		for (let i = 0; i < count; i++) {
			const [r, g, b] = [bytes[3 * i], bytes[3 * i + 1], bytes[3 * i + 2]];
			expect(r).toBeGreaterThanOrEqual(BLUE_END[0] * b);
			expect(g).toBeGreaterThanOrEqual(BLUE_END[1] * b);
		}
	});

	it('writes the floor into the shader', () => {
		expect(DUST_COLOUR_GLSL).toContain(
			`vec2(${BLUE_END[0].toFixed(2)}, ${BLUE_END[1].toFixed(2)})`
		);
	});
});

describe('the dust bound', () => {
	// The same cases are in tests/glow/test_light_law.py, so the grid and the
	// shader take out the same dust.
	it.each([
		['colour', 1.0, 5, 1.3 / 0.447],
		['brightness', 5.37, -5.8, (-5.8 - BRIGHTEST_M0) / K_G],
		['no colour', NaN, 3, 0],
		['bluer than the bluest', -1, 3, 0],
		['brighter than any star', 2, BRIGHTEST_M0 - 2, 0]
	])('follows the %s', (_name, bpRp, mag, bound) => {
		expect(dustBound(bpRp, mag)).toBeCloseTo(bound, 12);
	});

	it('is never negative, so the Sun reads no change', () => {
		const bpRp = Float32Array.from({ length: 500 }, (_, i) => -1.5 + i * 0.016);
		const mag = Float32Array.from({ length: 500 }, (_, i) => -14 + i * 0.05);
		const bytes = dustBounds(bpRp, mag, new Uint8Array(500));
		for (const byte of bytes) expect(Math.max(0, -decodeBound(byte))).toBe(0);
	});

	it('keeps a byte within half a step of the bound', () => {
		const bytes = dustBounds([0.5, 1.0, 3.0], [4, 5, 6], new Uint8Array(3));
		[0.8 / 0.447, 1.3 / 0.447, 3.3 / 0.447].forEach((bound, i) => {
			expect(Math.abs(decodeBound(bytes[i]) - bound)).toBeLessThanOrEqual(
				BOUND_MAX / 255 / 2 + 1e-9
			);
		});
	});

	it('holds the largest bound in the last byte', () => {
		expect(dustBounds([50], [50], new Uint8Array(1))[0]).toBe(255);
	});
});
