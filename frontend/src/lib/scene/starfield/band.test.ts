import { describe, expect, it } from 'vitest';
import {
	BASE_LIMIT_MAG,
	GLOW_CUT_MAG,
	GLOW_EXPOSURE_FROM_PC,
	GLOW_EXPOSURE_FULL_PC,
	PREFETCH_AU,
	RELEASE_AU,
	STARS_IN_AU,
	STARS_OUT_AU,
	boxDrawMag,
	dotLimit,
	glowExposureShare,
	glowLimitMag,
	starsTakeSky,
	targetLimitMag
} from './band';

describe('the skybox to starfield switch', () => {
	it('leaves the sky to the skybox inside it and gives it to the stars past it', () => {
		expect(starsTakeSky(1, true)).toBe(false);
		expect(starsTakeSky(STARS_OUT_AU * 0.99, true)).toBe(false);
		expect(starsTakeSky(STARS_IN_AU * (1 - Number.EPSILON), false)).toBe(true);
		expect(starsTakeSky(1e9, false)).toBe(true);
	});

	it('keeps the last answer between its two distances', () => {
		const between = Math.sqrt(STARS_OUT_AU * STARS_IN_AU);
		expect(starsTakeSky(between, true)).toBe(true);
		expect(starsTakeSky(between, false)).toBe(false);
	});

	it('starts loading before the switch and stops a little nearer in', () => {
		expect(PREFETCH_AU).toBeLessThan(STARS_OUT_AU);
		expect(RELEASE_AU).toBeLessThan(PREFETCH_AU);
	});
});

describe('the walk’s target limit', () => {
	it('is the zoom’s from any place', () => {
		for (const d of [0.01, 1, 300, 3_000, 49_600])
			expect(targetLimitMag(d)).toBe(7.5 + 5 * Math.log10(Math.max(d, 1)));
	});
});

describe('the limit of a dot', () => {
	it('keeps the drawn limit’s exposure near the Sun and takes the glow’s far from it', () => {
		expect(glowExposureShare(0)).toBe(0);
		expect(glowExposureShare(GLOW_EXPOSURE_FROM_PC)).toBe(0);
		expect(glowExposureShare(GLOW_EXPOSURE_FULL_PC)).toBe(1);
		expect(glowExposureShare(1e6)).toBe(1);
		for (const limit of [6, 12, 17, 25]) {
			expect(dotLimit(limit, 0, glowLimitMag(4))).toBe(limit);
			expect(dotLimit(limit, 1, glowLimitMag(4))).toBe(Math.min(limit, glowLimitMag(4)));
		}
		let last = Infinity;
		for (let d = GLOW_EXPOSURE_FROM_PC; d <= GLOW_EXPOSURE_FULL_PC; d += 10) {
			const limit = dotLimit(17, glowExposureShare(d), glowLimitMag(4));
			expect(limit).toBeLessThanOrEqual(last);
			last = limit;
		}
	});

	it('draws at the glow’s exposure the light the glow gives the star', () => {
		// A star at the limit of the Sun's exposure, times the gain.
		expect(glowLimitMag(1)).toBe(BASE_LIMIT_MAG);
		expect(glowLimitMag(10)).toBeCloseTo(BASE_LIMIT_MAG + 2.5, 12);
	});

	it('never falls under the glow’s cut, or under the drawn limit where that is lower', () => {
		for (const limit of [3, 6, GLOW_CUT_MAG, 9.1, 12, 30])
			for (const share of [0, 0.3, 0.9, 1])
				for (const gain of [0.25, 1, 4, 60]) {
					const drawn = dotLimit(limit, share, glowLimitMag(gain));
					expect(drawn).toBeGreaterThanOrEqual(Math.min(limit, GLOW_CUT_MAG));
					expect(drawn).toBeLessThanOrEqual(limit);
				}
	});

	it('tells the walk the drawn limit a box needs: no star of a box past it draws', () => {
		for (const magnitude of [2, 7, GLOW_CUT_MAG, 9, 13, 14, 15, 18])
			for (const share of [0, 0.25, 0.75, 1])
				for (const gain of [0.25, 1, 4, 60])
					for (const limit of [5, 8, 10, 14, 16, 20]) {
						const glow = glowLimitMag(gain);
						const needs = boxDrawMag(magnitude, share, glow);
						// The box's brightest star draws iff the limit is past what it needs.
						expect(magnitude < dotLimit(limit, share, glow)).toBe(limit > needs);
					}
	});
});
