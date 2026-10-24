import { describe, expect, it } from 'vitest';
import { PREFETCH_AU, RELEASE_AU, STARS_IN_AU, STARS_OUT_AU, starsTakeSky } from './band';

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
