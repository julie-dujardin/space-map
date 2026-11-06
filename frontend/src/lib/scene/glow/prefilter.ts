/**
 * Coarse copies of the light grid, so that the march can read the grid at the
 * size of what a sample stands for (`march.ts`). Near the Sun a cell is much
 * smaller than a step of the march. A sample then hits a bright cell or misses
 * it, and the glow flickers when the camera moves.
 *
 * Each copy averages the grid across directions in each shell. It does not
 * average across shells. Each copy is an octahedral map with its own ring past
 * the fold, so a read across the fold is continuous at each level. A cell is
 * the mean of the finer cells by solid angle, because the map is not
 * equal-area. So each copy keeps the light of the grid. The tint is a ratio,
 * so its mean takes the weight of the light that it is the tint of, L(M0 > 0).
 *
 * The copies are side by side in one 3D texture for each grid texture. The
 * third axis holds the shells of the grid.
 */

import { DataUtils } from 'three';

/** One copy: its cells on each side inside the ring, and its corner in the atlas. */
export interface CoarseLevel {
	inner: number;
	x: number;
	y: number;
}

export interface CoarseLayout {
	/** Texels of the atlas on each side. */
	width: number;
	height: number;
	/** The copies, fine to coarse. Copy k has about 2^k times the cell of the grid. */
	levels: CoarseLevel[];
}

/** The atlas of both grid textures, four half floats a texel, as the grid. */
export interface CoarseGrid {
	layout: CoarseLayout;
	a: Uint16Array;
	b: Uint16Array;
}

/** Cells on each side of the coarsest copy. */
const LEAST_INNER = 2;
/** Values a cell carries: the seven light edges, and the tint times L(M0 > 0). */
const CHANNELS = 8;

/** The copies of a grid of `size` texels on each side, or null if it has none. */
export function coarseLayout(size: number): CoarseLayout | null {
	const fine = size - 2;
	const inners: number[] = [];
	for (let k = 1; ; k++) {
		const inner = Math.max(Math.round(fine / 2 ** k), LEAST_INNER);
		if (inner >= (inners.at(-1) ?? fine)) break;
		inners.push(inner);
	}
	if (!inners.length) return null;
	// The first copy, the second at its side, and the others in a row under the second.
	const sides = inners.map((inner) => inner + 2);
	const levels: CoarseLevel[] = [{ inner: inners[0], x: 0, y: 0 }];
	if (inners.length > 1) levels.push({ inner: inners[1], x: sides[0], y: 0 });
	let x = sides[0];
	for (let k = 2; k < inners.length; k++) {
		levels.push({ inner: inners[k], x, y: sides[1] });
		x += sides[k];
	}
	return {
		width: Math.max(x, sides[0] + (sides[1] ?? 0)),
		height: Math.max(sides[0], (sides[1] ?? 0) + (sides[2] ?? 0)),
		levels
	};
}

/**
 * For each copy, the atlas coordinate of a grid coordinate `uv`: `uv * xy + zw`.
 * The grid of `size` texels and each copy map the same square of directions.
 */
export function coarseUniforms(layout: CoarseLayout, size: number): Float32Array {
	const fine = size - 2;
	const out = new Float32Array(layout.levels.length * 4);
	layout.levels.forEach(({ inner, x, y }, k) => {
		const ratio = inner / fine;
		out.set(
			[
				(size * ratio) / layout.width,
				(size * ratio) / layout.height,
				(x + 1 - ratio) / layout.width,
				(y + 1 - ratio) / layout.height
			],
			4 * k
		);
	});
	return out;
}

/** The cells of a finer map that each cell of a coarser one holds, with the share
 *  of each finer cell inside it. */
interface Taps {
	start: Int32Array;
	index: Int32Array;
	share: Float32Array;
}

function taps(from: number, to: number): Taps {
	const start = new Int32Array(to + 1);
	const index: number[] = [];
	const share: number[] = [];
	for (let j = 0; j < to; j++) {
		start[j] = index.length;
		const lo = (j * from) / to;
		const hi = ((j + 1) * from) / to;
		for (let i = Math.floor(lo); i < Math.ceil(hi); i++) {
			const part = Math.min(hi, i + 1) - Math.max(lo, i);
			if (part <= 0) continue;
			index.push(i);
			share.push(part);
		}
	}
	start[to] = index.length;
	return { start, index: Int32Array.from(index), share: Float32Array.from(share) };
}

/** Sum a square map of `from` cells on each side into one of `to` cells, along
 *  x and then y, with `channels` values a cell. */
function resample(
	source: Float32Array,
	from: number,
	to: number,
	{ start, index, share }: Taps,
	channels: number,
	along: Float32Array,
	out: Float32Array
): void {
	along.fill(0, 0, from * to * channels);
	for (let y = 0; y < from; y++) {
		for (let j = 0; j < to; j++) {
			const o = (y * to + j) * channels;
			for (let t = start[j]; t < start[j + 1]; t++) {
				const s = (y * from + index[t]) * channels;
				const w = share[t];
				for (let c = 0; c < channels; c++) along[o + c] += source[s + c] * w;
			}
		}
	}
	out.fill(0, 0, to * to * channels);
	for (let j = 0; j < to; j++) {
		for (let t = start[j]; t < start[j + 1]; t++) {
			const w = share[t];
			const s0 = index[t] * to * channels;
			const o0 = j * to * channels;
			for (let k = 0; k < to * channels; k++) out[o0 + k] += along[s0 + k] * w;
		}
	}
}

/** Solid angle of each cell of a map with `inner` cells a side, to a constant
 *  factor: dΩ = dA / |p|³ with p on the octahedron. */
function solidAngles(inner: number): Float32Array {
	const out = new Float32Array(inner * inner);
	for (let y = 0; y < inner; y++) {
		for (let x = 0; x < inner; x++) {
			const qx = Math.abs(((x + 0.5) / inner) * 2 - 1);
			const qy = Math.abs(((y + 0.5) / inner) * 2 - 1);
			const south = qx + qy > 1;
			const px = south ? 1 - qy : qx;
			const py = south ? 1 - qx : qy;
			const pz = 1 - px - py;
			out[y * inner + x] = (px * px + py * py + pz * pz) ** -1.5;
		}
	}
	return out;
}

/**
 * For each texel of a map of `side` texels, the inner cell that holds its ray:
 * itself inside the ring, the cell past the fold on the ring. This is the
 * export's rule for the grid's ring.
 */
function ringSources(side: number): Int32Array {
	const inner = side - 2;
	const out = new Int32Array(side * side);
	const sign = (v: number) => (v >= 0 ? 1 : -1);
	const cell = (q: number) => Math.min(Math.max(Math.floor(((q + 1) / 2) * inner), 0), inner - 1);
	for (let r = 0; r < side; r++) {
		for (let c = 0; c < side; c++) {
			let qx = (2 * c - 1) / inner - 1;
			let qy = (2 * r - 1) / inner - 1;
			if (Math.abs(qx) > 1) [qx, qy] = [2 * sign(qx) - qx, -qy];
			if (Math.abs(qy) > 1) [qx, qy] = [-qx, 2 * sign(qy) - qy];
			out[r * side + c] = cell(qy) * inner + cell(qx);
		}
	}
	return out;
}

let halfTable: Float32Array | null = null;
const floatView = new Float32Array(1);
const bitsView = new Uint32Array(floatView.buffer);

/** The half float nearest to a value that is not negative, at most the largest half. */
function toHalf(value: number): number {
	floatView[0] = Math.min(value, 65504);
	const bits = bitsView[0];
	const exponent = ((bits >>> 23) & 0xff) - 112;
	const mantissa = bits & 0x7fffff;
	if (exponent <= 0) {
		if (exponent < -10) return 0;
		const shift = 14 - exponent;
		const full = mantissa | 0x800000;
		const half = full >>> shift;
		const rest = full & ((1 << shift) - 1);
		const middle = 1 << (shift - 1);
		return half + (rest > middle || (rest === middle && (half & 1) === 1) ? 1 : 0);
	}
	const half = (exponent << 10) | (mantissa >>> 13);
	const rest = mantissa & 0x1fff;
	return half + (rest > 0x1000 || (rest === 0x1000 && (half & 1) === 1) ? 1 : 0);
}

/**
 * The coarse copies of a grid tier of `size` texels and `shells` shells, from
 * its two textures. `pause` runs after each shell, so a caller can yield.
 */
export async function prefilterGrid(
	size: number,
	shells: number,
	a: Uint16Array,
	b: Uint16Array,
	neutralTint: number,
	pause: () => Promise<void> = async () => {}
): Promise<CoarseGrid | null> {
	const layout = coarseLayout(size);
	if (!layout) return null;
	halfTable ??= Float32Array.from({ length: 65536 }, (_, i) => DataUtils.fromHalfFloat(i));
	const half = halfTable;
	const { width, height, levels } = layout;
	const fine = size - 2;
	const sides = [fine, ...levels.map((l) => l.inner)];
	const steps = levels.map((_, k) => taps(sides[k], sides[k + 1]));
	const sources = levels.map((l) => ringSources(l.inner + 2));
	const along = new Float32Array(fine * sides[1] * CHANNELS);
	// The solid angle of each cell at each level, as a sum of the finer cells.
	const angles = [solidAngles(fine)];
	for (let k = 0; k < levels.length; k++) {
		const out = new Float32Array(sides[k + 1] ** 2);
		resample(angles[k], sides[k], sides[k + 1], steps[k], 1, along, out);
		angles.push(out);
	}
	const sums = sides.map((side) => new Float32Array(side * side * CHANNELS));
	const outA = new Uint16Array(width * height * shells * 4);
	const outB = new Uint16Array(width * height * shells * 4);
	const neutral = toHalf(neutralTint);
	for (let shell = 0; shell < shells; shell++) {
		// Light times solid angle, so that the copies keep the light.
		const top = sums[0];
		const angle = angles[0];
		for (let y = 0; y < fine; y++) {
			for (let x = 0; x < fine; x++) {
				const i = y * fine + x;
				const t = ((shell * size + y + 1) * size + x + 1) * 4;
				const w = angle[i];
				const o = i * CHANNELS;
				for (let c = 0; c < 4; c++) top[o + c] = half[a[t + c]] * w;
				for (let c = 0; c < 3; c++) top[o + 4 + c] = half[b[t + c]] * w;
				top[o + 7] = half[b[t + 3]] * top[o + 3];
			}
		}
		for (let k = 0; k < levels.length; k++) {
			const side = sides[k + 1];
			resample(sums[k], sides[k], side, steps[k], CHANNELS, along, sums[k + 1]);
			const sum = sums[k + 1];
			const weight = angles[k + 1];
			const source = sources[k];
			const { x: x0, y: y0 } = levels[k];
			for (let r = 0; r < side + 2; r++) {
				for (let c = 0; c < side + 2; c++) {
					const i = source[r * (side + 2) + c];
					const o = i * CHANNELS;
					const w = 1 / weight[i];
					const t = ((shell * height + y0 + r) * width + x0 + c) * 4;
					for (let ch = 0; ch < 4; ch++) outA[t + ch] = toHalf(sum[o + ch] * w);
					for (let ch = 0; ch < 3; ch++) outB[t + ch] = toHalf(sum[o + 4 + ch] * w);
					outB[t + 3] = sum[o + 3] > 0 ? toHalf(sum[o + 7] / sum[o + 3]) : neutral;
				}
			}
		}
		await pause();
	}
	return { layout, a: outA, b: outB };
}
