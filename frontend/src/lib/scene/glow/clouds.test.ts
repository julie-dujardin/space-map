import { describe, expect, it } from 'vitest';
import { DataUtils } from 'three';
import type { Vec3 } from '$lib/scene/dust/octahedral';
import { MAX_CLOUDS, cloudBoxes } from './clouds';
import type { GlowModel, ModelVolume } from './model';

/** An outer box of 32 texels of 4 kpc a side about the centre, as the served
 *  block has it at a small size. */
const N = 32;
const MODEL = {
	centre_pc: [8277, 0, -21],
	boxes: {
		inner: { half_extent_pc: [24000, 24000, 3000], z_map: 'asinh', z_scale_pc: 150 },
		outer: { half_extent_pc: [64000, 64000, 64000], z_map: 'linear', z_scale_pc: 0 }
	}
} as unknown as GlowModel;

/** A halo falling as r^-3 about the centre, and Gaussian lumps at `lumps`
 *  (pc from the centre, sigma, peak). */
function volume(lumps: [Vec3, number, number][]): ModelVolume {
	const data = new Uint16Array(N * N * N);
	for (let z = 0; z < N; z++)
		for (let y = 0; y < N; y++)
			for (let x = 0; x < N; x++) {
				const p = [x, y, z].map((i) => (i + 0.5) * 4000 - 64000);
				const r = Math.max(Math.hypot(...p), 10000);
				let v = (r / 10000) ** -3;
				for (const [c, sigma, peak] of lumps) {
					const d2 = p.reduce((s, v, k) => s + (v - c[k]) ** 2, 0);
					v += peak * Math.exp(-d2 / (2 * sigma * sigma));
				}
				data[x + N * (y + N * z)] = DataUtils.toHalfFloat(Math.min(v, 60000));
			}
	const outer = { size: [N, N, N] as Vec3, data };
	return { inner: { size: [2, 2, 2], data: new Uint16Array(8) }, outer };
}

const inside = (p: Vec3, box: { lo: Vec3; hi: Vec3 }) =>
	p.every((v, k) => v >= box.lo[k] && v <= box.hi[k]);

describe('cloudBoxes', () => {
	it('finds the lumps out of the inner box that hold far more than the halo, the brightest first', () => {
		const lmc: Vec3 = [-700, -41000, -27000];
		const smc: Vec3 = [16000, -37000, -43000];
		const boxes = cloudBoxes(
			MODEL,
			volume([
				[lmc, 2000, 60],
				[smc, 1500, 30]
			])
		);
		expect(boxes).toHaveLength(2);
		const onNest = (p: Vec3): Vec3 => [p[0] + 8277, p[1], p[2] - 21];
		expect(inside(onNest(lmc), boxes[0])).toBe(true);
		expect(inside(onNest(smc), boxes[1])).toBe(true);
		expect(inside(onNest(smc), boxes[0])).toBe(false);
		// A box holds its lump past the texels over the threshold, by the filter's reach.
		for (const box of boxes)
			for (let k = 0; k < 3; k++) expect(box.hi[k] - box.lo[k]).toBeGreaterThan(8000);
	});

	it('leaves the halo and faint lumps to the outer span', () => {
		expect(cloudBoxes(MODEL, volume([]))).toEqual([]);
		expect(cloudBoxes(MODEL, volume([[[0, -40000, -30000], 3000, 0.02]]))).toEqual([]);
	});

	it('keeps at most a few boxes', () => {
		const lumps: [Vec3, number, number][] = [-40000, -15000, 15000, 40000].flatMap((x) => [
			[[x, -45000, -30000], 2000, 20],
			[[x, 45000, 30000], 2000, 20]
		]);
		expect(cloudBoxes(MODEL, volume(lumps))).toHaveLength(MAX_CLOUDS);
	});

	it('has none for a box that is not linear on each axis', () => {
		const model = {
			...MODEL,
			boxes: { ...MODEL.boxes, outer: { ...MODEL.boxes.outer, z_map: 'asinh', z_scale_pc: 150 } }
		} as GlowModel;
		expect(cloudBoxes(model, volume([[[0, -40000, -30000], 2000, 20]]))).toEqual([]);
	});
});
