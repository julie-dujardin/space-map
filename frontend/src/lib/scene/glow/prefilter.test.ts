/**
 * The coarse copies of the light grid: their place in the atlas, the light
 * they keep by solid angle, the ring past the fold and the weight of the tint.
 */

import { describe, expect, it } from 'vitest';
import { DataUtils } from 'three';
import { coarseLayout, coarseUniforms, prefilterGrid, type CoarseGrid } from './prefilter';

const NEUTRAL = 0.46;

/** A grid of `size` texels and `shells` shells, from a value per texel and channel. */
function grid(
	size: number,
	shells: number,
	value: (shell: number, row: number, column: number, channel: number) => number
): Uint16Array {
	const out = new Uint16Array(size * size * shells * 4);
	for (let s = 0; s < shells; s++)
		for (let r = 0; r < size; r++)
			for (let c = 0; c < size; c++)
				for (let ch = 0; ch < 4; ch++)
					out[((s * size + r) * size + c) * 4 + ch] = DataUtils.toHalfFloat(value(s, r, c, ch));
	return out;
}

/** A texel of copy `level`, in its own rows and columns with the ring. */
function texel(
	coarse: CoarseGrid,
	which: 'a' | 'b',
	level: number,
	shell: number,
	r: number,
	c: number
) {
	const { width, height, levels } = coarse.layout;
	const { x, y } = levels[level];
	const at = ((shell * height + y + r) * width + x + c) * 4;
	return Array.from(coarse[which].subarray(at, at + 4), (h) => DataUtils.fromHalfFloat(h));
}

/** Solid angle of each inner cell of the grid, to a constant factor, as the
 *  prefilter takes it. */
function angles(inner: number): number[] {
	const out: number[] = [];
	for (let y = 0; y < inner; y++)
		for (let x = 0; x < inner; x++) {
			const qx = Math.abs(((x + 0.5) / inner) * 2 - 1);
			const qy = Math.abs(((y + 0.5) / inner) * 2 - 1);
			const south = qx + qy > 1;
			const px = south ? 1 - qy : qx;
			const py = south ? 1 - qx : qy;
			out.push((px * px + py * py + (1 - px - py) ** 2) ** -1.5);
		}
	return out;
}

describe('the layout of the copies', () => {
	it('halves the cells to a copy of two cells a side', () => {
		expect(coarseLayout(256)?.levels.map((l) => l.inner)).toEqual([127, 64, 32, 16, 8, 4, 2]);
		expect(coarseLayout(128)?.levels.map((l) => l.inner)).toEqual([63, 32, 16, 8, 4, 2]);
	});

	it('is none for a grid too small to halve', () => {
		expect(coarseLayout(2)).toBeNull();
		expect(coarseLayout(4)).toBeNull();
	});

	it('puts each copy inside the atlas, with no two on one texel', () => {
		for (const size of [8, 18, 128, 256]) {
			const layout = coarseLayout(size)!;
			const used = new Uint8Array(layout.width * layout.height);
			for (const { inner, x, y } of layout.levels) {
				expect(x + inner + 2).toBeLessThanOrEqual(layout.width);
				expect(y + inner + 2).toBeLessThanOrEqual(layout.height);
				for (let r = y; r < y + inner + 2; r++)
					for (let c = x; c < x + inner + 2; c++) used[r * layout.width + c]++;
			}
			expect(Math.max(...used)).toBe(1);
		}
	});

	it('maps a grid coordinate to the same direction in each copy', () => {
		const size = 256;
		const layout = coarseLayout(size)!;
		const map = coarseUniforms(layout, size);
		for (const q of [-1, -0.3, 0.5, 1]) {
			const uv = (q * 0.5 + 0.5) * ((size - 2) / size) + 1 / size;
			layout.levels.forEach(({ inner, x, y }, k) => {
				const u = (uv * map[4 * k] + map[4 * k + 2]) * layout.width - x;
				const v = (uv * map[4 * k + 1] + map[4 * k + 3]) * layout.height - y;
				expect(u).toBeCloseTo((q * 0.5 + 0.5) * inner + 1, 4);
				expect(v).toBeCloseTo((q * 0.5 + 0.5) * inner + 1, 4);
			});
		}
	});
});

describe('the copies', () => {
	it('keep the light of each shell by solid angle', async () => {
		const size = 18;
		const inner = size - 2;
		const a = grid(size, 2, (s, r, c, ch) => ((r * 7 + c * 3 + s * 5 + ch) % 11) * 0.25);
		const b = grid(size, 2, (s, r, c, ch) => (ch === 3 ? 0.3 : ((r + 2 * c + s) % 5) * 0.5));
		const coarse = (await prefilterGrid(size, 2, a, b, NEUTRAL))!;
		const fine = angles(inner);
		coarse.layout.levels.forEach((level, k) => {
			const block = inner / level.inner;
			for (let shell = 0; shell < 2; shell++) {
				let before = 0;
				let after = 0;
				for (let y = 0; y < inner; y++)
					for (let x = 0; x < inner; x++) {
						const value = DataUtils.fromHalfFloat(a[((shell * size + y + 1) * size + x + 1) * 4]);
						const w = fine[y * inner + x];
						before += value * w;
						const copy = texel(
							coarse,
							'a',
							k,
							shell,
							Math.floor(y / block) + 1,
							Math.floor(x / block) + 1
						);
						after += copy[0] * w;
					}
				expect(after / before).toBeCloseTo(1, 3);
			}
		});
	});

	it('hold a uniform grid as it is, on the ring too', async () => {
		const size = 10;
		const a = grid(size, 1, (_s, _r, _c, ch) => 4 - ch);
		const b = grid(size, 1, (_s, _r, _c, ch) => (ch === 3 ? 0.25 : 0.5));
		const coarse = (await prefilterGrid(size, 1, a, b, NEUTRAL))!;
		coarse.layout.levels.forEach(({ inner }, k) => {
			for (let r = 0; r < inner + 2; r++)
				for (let c = 0; c < inner + 2; c++) {
					expect(texel(coarse, 'a', k, 0, r, c)).toEqual([4, 3, 2, 1]);
					expect(texel(coarse, 'b', k, 0, r, c)).toEqual([0.5, 0.5, 0.5, 0.25]);
				}
		});
	});

	it('hold on the ring the cell past the fold', async () => {
		const size = 18;
		const a = grid(size, 1, (_s, r, c) => r * size + c);
		const b = grid(size, 1, () => 0);
		const coarse = (await prefilterGrid(size, 1, a, b, NEUTRAL))!;
		coarse.layout.levels.forEach(({ inner }, k) => {
			const side = inner + 2;
			const at = (r: number, c: number) => texel(coarse, 'a', k, 0, r, c)[0];
			for (let i = 1; i < side - 1; i++) {
				expect(at(0, i)).toBe(at(1, side - 1 - i));
				expect(at(side - 1, i)).toBe(at(side - 2, side - 1 - i));
				expect(at(i, 0)).toBe(at(side - 1 - i, 1));
				expect(at(i, side - 1)).toBe(at(side - 1 - i, side - 2));
			}
			expect(at(0, 0)).toBe(at(side - 2, side - 2));
		});
	});

	it('weigh the tint by the light it is the tint of', async () => {
		const size = 10;
		// The first three inner columns have no light of M0 > 0, and a tint that must not count.
		const a = grid(size, 1, (_s, _r, c, ch) => (ch === 3 && c <= 3 ? 0 : 1));
		const b = grid(size, 1, (_s, _r, c, ch) => (ch === 3 ? (c <= 3 ? 0.9 : 0.3) : 1));
		const coarse = (await prefilterGrid(size, 1, a, b, NEUTRAL))!;
		const tint = (level: number, c: number) => texel(coarse, 'b', level, 0, 1, c)[3];
		// The first copy has four cells a side: the first holds no such light, the
		// second holds a column of each.
		expect(tint(0, 1)).toBe(DataUtils.fromHalfFloat(DataUtils.toHalfFloat(NEUTRAL)));
		expect(tint(0, 2)).toBeCloseTo(0.3, 3);
		expect(tint(1, 1)).toBeCloseTo(0.3, 3);
	});

	it('come with a pause after each shell', async () => {
		let pauses = 0;
		const a = grid(6, 3, () => 1);
		await prefilterGrid(6, 3, a, a, NEUTRAL, async () => {
			pauses++;
		});
		expect(pauses).toBe(3);
	});
});
