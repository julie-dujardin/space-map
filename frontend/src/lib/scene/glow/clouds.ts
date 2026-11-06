/**
 * Boxes about the compact lights of the model's outer box: the Magellanic
 * Clouds. The march's outer span takes few steps over hundreds of kpc, so from
 * far a ray takes one sample in a Cloud or none, and the jitter draws the Cloud
 * as grain. In these boxes the march takes steps of its own (`march.ts`).
 *
 * They come from the model's data, not from a list of objects: the texels out
 * of the inner box that hold far more light than the halo at their distance from
 * the Galactic centre, in connected parts that hold a visible share of the outer
 * box's light.
 */

import { DataUtils } from 'three';
import type { Vec3 } from '$lib/scene/dust/octahedral';
import type { GlowModel, ModelVolume } from './model';

/** A box on nest axes (pc from the Sun). */
export interface CloudBox {
	lo: Vec3;
	hi: Vec3;
}

/** Most boxes the march takes. */
export const MAX_CLOUDS = 4;
/** A texel is a Cloud's where it holds this many times the median of its shell. */
const OVER_HALO = 10;
/** Least share of the light out of the inner box that a part holds. */
const LEAST_SHARE = 0.02;
/** Texels on each side of a part that its box also holds, for the filter's reach. */
const PAD_TEXELS = 1;
/** Texels on each axis between two that the shell medians read. */
const MEDIAN_STRIDE = 2;

let halfTable: Float32Array | null = null;

function halves(data: Uint16Array): Float32Array {
	halfTable ??= Float32Array.from({ length: 65536 }, (_, i) => DataUtils.fromHalfFloat(i));
	const table = halfTable;
	const out = new Float32Array(data.length);
	for (let i = 0; i < data.length; i++) out[i] = table[data[i]];
	return out;
}

/** The Cloud boxes of the model's outer volume, the brightest first. */
export function cloudBoxes(model: GlowModel, volume: ModelVolume): CloudBox[] {
	// The texel of a place is found by a linear map on each axis only.
	if (model.boxes.outer.z_map !== 'linear') return [];
	const [nx, ny, nz] = volume.outer.size;
	const half = model.boxes.outer.half_extent_pc;
	const inner = model.boxes.inner.half_extent_pc;
	const cell = [(2 * half[0]) / nx, (2 * half[1]) / ny, (2 * half[2]) / nz];
	const values = halves(volume.outer.data);
	const at = (i: number, k: number) => (i + 0.5) * cell[k] - half[k];
	const shellOf = (x: number, y: number, z: number) =>
		Math.floor(Math.hypot(at(x, 0), at(y, 1), at(z, 2)) / cell[0]);
	const outside = (x: number, y: number, z: number) =>
		Math.abs(at(x, 0)) > inner[0] || Math.abs(at(y, 1)) > inner[1] || Math.abs(at(z, 2)) > inner[2];

	// The halo at each distance from the centre: the median of its shell.
	const shells: number[][] = [];
	for (let z = 0; z < nz; z += MEDIAN_STRIDE)
		for (let y = 0; y < ny; y += MEDIAN_STRIDE)
			for (let x = 0; x < nx; x += MEDIAN_STRIDE)
				(shells[shellOf(x, y, z)] ??= []).push(values[x + nx * (y + ny * z)]);
	const halo = shells.map((s) => {
		const sorted = Float32Array.from(s).sort();
		return sorted[sorted.length >> 1];
	});

	const marked = new Uint8Array(values.length);
	let outsideLight = 0;
	for (let z = 0; z < nz; z++)
		for (let y = 0; y < ny; y++)
			for (let x = 0; x < nx; x++) {
				if (!outside(x, y, z)) continue;
				const i = x + nx * (y + ny * z);
				outsideLight += values[i];
				const h = halo[shellOf(x, y, z)];
				if (h !== undefined && values[i] > OVER_HALO * Math.max(h, 1e-30)) marked[i] = 1;
			}

	const parts: { light: number; lo: number[]; hi: number[] }[] = [];
	const stack: number[] = [];
	for (let start = 0; start < values.length; start++) {
		if (marked[start] !== 1) continue;
		marked[start] = 2;
		stack.push(start);
		const part = { light: 0, lo: [nx, ny, nz], hi: [-1, -1, -1] };
		while (stack.length) {
			const i = stack.pop() as number;
			const x = i % nx;
			const y = Math.floor(i / nx) % ny;
			const z = Math.floor(i / (nx * ny));
			part.light += values[i];
			[x, y, z].forEach((v, k) => {
				part.lo[k] = Math.min(part.lo[k], v);
				part.hi[k] = Math.max(part.hi[k], v);
			});
			for (let dz = -1; dz <= 1; dz++)
				for (let dy = -1; dy <= 1; dy++)
					for (let dx = -1; dx <= 1; dx++) {
						const a = x + dx;
						const b = y + dy;
						const c = z + dz;
						if (a < 0 || b < 0 || c < 0 || a >= nx || b >= ny || c >= nz) continue;
						const j = a + nx * (b + ny * c);
						if (marked[j] !== 1) continue;
						marked[j] = 2;
						stack.push(j);
					}
		}
		parts.push(part);
	}

	const centre = model.centre_pc;
	return parts
		.filter((p) => p.light >= LEAST_SHARE * outsideLight)
		.sort((a, b) => b.light - a.light)
		.slice(0, MAX_CLOUDS)
		.map(({ lo, hi }) => ({
			lo: [0, 1, 2].map((k) => (lo[k] - PAD_TEXELS) * cell[k] - half[k] + centre[k]) as Vec3,
			hi: [0, 1, 2].map((k) => (hi[k] + 1 + PAD_TEXELS) * cell[k] - half[k] + centre[k]) as Vec3
		}));
}
