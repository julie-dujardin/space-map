import { describe, expect, it } from 'vitest';
import { tapsPerSide, texelsPerPixel } from './cube-sky';
import { fitFrame } from './frame';

describe('the taps of a pixel of the cube', () => {
	it('reads each texel of a pixel that holds a few', () => {
		expect(tapsPerSide(0.4)).toBe(1);
		expect(tapsPerSide(2.2)).toBe(3);
		expect(tapsPerSide(8)).toBe(8);
	});

	it('holds at its limit on a wide frame, where each tap reads a mip', () => {
		expect(tapsPerSide(79)).toBe(tapsPerSide(8));
	});

	it('counts more texels in a pixel of a wider frame, and fewer in a sharper picture', () => {
		const stars = (deg: number) => {
			const half = (deg * Math.PI) / 360;
			return [
				[Math.cos(half), Math.sin(half), 0],
				[Math.cos(half), -Math.sin(half), 0]
			] as [number, number, number][];
		};
		const narrow = fitFrame(stars(10), { width: 150, height: 112 });
		const wide = fitFrame(stars(100), { width: 150, height: 112 });
		expect(texelsPerPixel(narrow, 150, 4096)).toBeLessThan(8);
		expect(texelsPerPixel(wide, 150, 4096)).toBeGreaterThan(30);
		expect(texelsPerPixel(wide, 300, 4096)).toBeCloseTo(texelsPerPixel(wide, 150, 4096) / 2, 9);
		expect(texelsPerPixel(wide, 150, 1024)).toBeCloseTo(texelsPerPixel(wide, 150, 4096) / 4, 9);
	});
});
