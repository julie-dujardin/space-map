import { describe, expect, it } from 'vitest';
import { AU_KM, KM_PER_PC } from '$lib/math/units';
import { STARS_IN_AU } from '$lib/scene/starfield/band';
import {
	ADAPT_CLOSE,
	ADAPT_POWER,
	ADAPT_REST_MS,
	MAX_GAIN,
	MIN_GAIN,
	PLACE_GAIN_MAG,
	SUN_EXPOSURE,
	adaptedGain,
	eyeKeep,
	placeGain
} from './exposure';

describe('placeGain', () => {
	const join = (STARS_IN_AU * AU_KM) / KM_PER_PC;
	const mag = (gain: number) => 2.5 * Math.log10(gain);

	it('is one at the join and inside it, and rises with no step past it', () => {
		expect(placeGain([0, 0, 0])).toBe(1);
		expect(placeGain([join, 0, 0])).toBe(1);
		expect(placeGain([0, 0, -join])).toBe(1);
		expect(placeGain([join * 1.05, 0, 0]) - 1).toBeLessThan(1e-8);
	});

	it('rises with distance in the plane to the band’s gain deep in the disc', () => {
		expect(mag(placeGain([-1, 0, 0.2]))).toBeCloseTo(0.025, 3);
		expect(mag(placeGain([-100, 0, 10]))).toBeGreaterThan(PLACE_GAIN_MAG - 0.02);
		expect(mag(placeGain([-1000, 300, 100]))).toBeGreaterThan(PLACE_GAIN_MAG - 0.01);
		let last = 1;
		for (let d = 1e-3; d < 1e5; d *= 1.2) {
			const gain = placeGain([d, 0, 0]);
			expect(gain).toBeGreaterThanOrEqual(last);
			expect(mag(gain)).toBeLessThanOrEqual(PLACE_GAIN_MAG + 1e-12);
			last = gain;
		}
	});

	it('falls with height above the plane, where the eye brightens the glow', () => {
		expect(placeGain([0, 0, 8000])).toBeLessThan(1.4);
		expect(placeGain([-28000, 0, 6000])).toBeLessThan(1.6);
		expect(placeGain([0, 0, -8000])).toBe(placeGain([0, 0, 8000]));
	});
});

describe('adaptedGain', () => {
	it('is one when the map is the Sun’s, at the stars’ exposure at the skybox’s limit', () => {
		expect(SUN_EXPOSURE).toBeCloseTo(9.63e-5, 7);
		expect(adaptedGain(22.4, 22.4)).toBeCloseTo(1, 12);
	});

	it('takes back only part of a change in brightness, within its bounds', () => {
		expect(adaptedGain(1, 16)).toBeCloseTo(16 ** ADAPT_POWER, 12);
		expect(adaptedGain(1e-9, 1)).toBe(MAX_GAIN);
		expect(adaptedGain(1e9, 1)).toBe(MIN_GAIN);
		let last = Infinity;
		for (let mean = 0.01; mean < 100; mean *= 1.5) {
			const gain = adaptedGain(mean, 1);
			expect(gain).toBeLessThanOrEqual(last);
			last = gain;
		}
	});

	it('is one without a mean', () => {
		expect(adaptedGain(0, 1)).toBe(1);
		expect(adaptedGain(1, Number.NaN)).toBe(1);
	});
});

describe('the eye’s two stages, as eye.ts runs them', () => {
	/** Log gain over frames of 16 ms after the target moves from 0 to `goal`. */
	function ease(goal: number, ms: number): number[] {
		const keep = eyeKeep(16);
		let first = 0;
		let second = 0;
		const seen = [0];
		for (let t = 16; t <= ms; t += 16) {
			first = goal + (first - goal) * keep;
			second = first + (second - first) * keep;
			seen.push(second);
		}
		return seen;
	}

	it('takes seconds, starts and ends slowly, and never steps', () => {
		const goal = Math.log(4);
		const seen = ease(goal, ADAPT_REST_MS);
		const steps = seen.slice(1).map((x, i) => x - seen[i]);
		expect(Math.min(...steps)).toBeGreaterThanOrEqual(0);
		expect(steps[0]).toBeLessThan(steps[5]);
		expect(Math.max(...steps)).toBeLessThan(0.02);
		expect(seen.findIndex((x) => x > goal / 2) * 16).toBeGreaterThan(500);
		// By its time of rest it has covered all but 0.05% of the change.
		expect(goal - seen.at(-1)!).toBeLessThan(5e-4 * goal);
	});

	it('comes close enough to stop in a time that grows with the change', () => {
		const closeMs = (gain: number) =>
			ease(Math.log(gain), ADAPT_REST_MS).findIndex(
				(x) => Math.log(gain) - x < Math.log1p(ADAPT_CLOSE)
			) * 16;
		expect(closeMs(1.004)).toBe(0);
		expect(closeMs(1.05)).toBeLessThan(2100);
		expect(closeMs(2.84)).toBeLessThan(3900);
		// The widest change the bounds allow is close by the time of rest.
		expect(closeMs(MAX_GAIN / MIN_GAIN)).toBeGreaterThan(0);
		expect(closeMs(MAX_GAIN / MIN_GAIN)).toBeLessThan(ADAPT_REST_MS);
	});

	it('keeps nothing of a frame of no length taken at once', () => {
		expect(eyeKeep(0)).toBe(1);
		expect(eyeKeep(1e9)).toBe(0);
	});
});
