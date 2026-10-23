import { describe, expect, it } from 'vitest';
import { BAND_END_AU, BAND_START_AU, PREFETCH_AU, RELEASE_AU, bandShare } from './band';

describe('the skybox to starfield band', () => {
	it('is all skybox up to its start and all starfield past its end', () => {
		expect(bandShare(1)).toBe(0);
		expect(bandShare(BAND_START_AU)).toBe(0);
		expect(bandShare(BAND_END_AU)).toBe(1);
		expect(bandShare(1e9)).toBe(1);
	});

	it('is half way at the middle of its log scale, and rises all along', () => {
		expect(bandShare(Math.sqrt(BAND_START_AU * BAND_END_AU))).toBeCloseTo(0.5, 12);
		let last = 0;
		for (let au = BAND_START_AU; au <= BAND_END_AU; au *= 1.05) {
			expect(bandShare(au)).toBeGreaterThanOrEqual(last);
			last = bandShare(au);
		}
	});

	it('starts loading before the band and stops a little nearer in', () => {
		expect(PREFETCH_AU).toBeLessThan(BAND_START_AU);
		expect(RELEASE_AU).toBeLessThan(PREFETCH_AU);
	});
});
