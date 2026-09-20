import { describe, expect, it } from 'vitest';
import { aimAtCoverage, type CoverageMask } from './coverage';

/** A mask covering image azimuths `[fromAz, toAz)` clockwise and elevations
 *  `[bottomEl, topEl]`. */
function mask(fromAz: number, toAz: number, bottomEl: number, topEl: number): CoverageMask {
	const width = 72;
	const height = 36;
	const covered = new Uint8Array(width * height);
	const span = toAz - fromAz === 360 ? 360 : (((toAz - fromAz) % 360) + 360) % 360;
	for (let y = 0; y < height; y++) {
		const el = 90 - ((y + 0.5) * 180) / height;
		if (el < bottomEl || el > topEl) continue;
		for (let x = 0; x < width; x++) {
			const az = ((x + 0.5) * 360) / width;
			if ((((az - fromAz) % 360) + 360) % 360 < span) covered[y * width + x] = 1;
		}
	}
	return { width, height, covered };
}

const frame = { northOffsetDeg: 0, hfovDeg: 100, vfovDeg: 75 };
const level = { heading: 0, pitch: 0 };

describe('aimAtCoverage', () => {
	it('faces the middle of a partial sweep, across the seam too', () => {
		expect(aimAtCoverage(mask(200, 260, -30, 20), level, frame).heading).toBeCloseTo(230, 0);
		expect(aimAtCoverage(mask(300, 60, -30, 20), level, frame).heading).toBeCloseTo(0, 0);
	});

	it('reads the heading from where north is on the texture', () => {
		const aim = aimAtCoverage(mask(200, 260, -30, 20), level, { ...frame, northOffsetDeg: 50 });
		expect(aim.heading).toBeCloseTo(180, 0);
	});

	it('keeps the heading when the imagery goes all round', () => {
		const view = { heading: 123, pitch: 0 };
		expect(aimAtCoverage(mask(0, 360, -60, 20), view, frame).heading).toBe(123);
		expect(aimAtCoverage(mask(10, 5, -60, 20), view, frame).heading).toBe(123);
	});

	it('keeps a pitch that lies inside the band and pulls one that does not just inside', () => {
		expect(aimAtCoverage(mask(0, 360, -60, 40), level, frame).pitch).toBe(0);
		expect(aimAtCoverage(mask(0, 360, -70, -20), level, frame).pitch).toBeCloseTo(-45, 0);
		expect(
			aimAtCoverage(mask(0, 360, -70, -20), { heading: 0, pitch: -80 }, frame).pitch
		).toBeCloseTo(-45, 0);
		expect(aimAtCoverage(mask(0, 360, 10, 60), level, frame).pitch).toBeCloseTo(35, 0);
	});

	it('pitches to the band ahead, not to imagery behind the reader', () => {
		const behind = mask(150, 210, -70, -40);
		const ahead = mask(330, 30, -20, 20);
		const both: CoverageMask = {
			...ahead,
			covered: ahead.covered.map((c, i) => c | behind.covered[i])
		};
		const aim = aimAtCoverage(both, level, frame);
		expect(aim.heading).toBeCloseTo(0, 0);
		expect(aim.pitch).toBe(0);
	});

	it('leaves an empty texture alone', () => {
		const view = { heading: 40, pitch: -10 };
		expect(aimAtCoverage(mask(0, 0, 0, 0), view, frame)).toEqual(view);
	});
});
