/**
 * The split table of a record table (`docs/export-format/extrasolar.md`,
 * "Record tiles"). One bit per HEALPix pixel of the tree in pre-order, from
 * root 0 to root 11: set when the pixel splits into its four children. The
 * leaves come out in cell order, so the tile of a cell is the last leaf whose
 * first cell is not above it.
 */

import { ContainerFormatError } from './container';
import { CELL_LEVEL } from './ids';

const ROOTS = 12;

export interface Bits {
	readonly length: number;
	get(i: number): boolean;
}

/** One record tile: a pixel at a level. */
export type TileKey = { level: number; pixel: number };

export class SplitTree {
	private constructor(
		/** First cell of each leaf, ascending. */
		readonly first: Uint32Array,
		readonly level: Uint8Array
	) {}

	static fromBits(bits: Bits): SplitTree {
		const first: number[] = [];
		const level: number[] = [];
		let at = 0;
		const visit = (depth: number, pixel: number): void => {
			if (at >= bits.length) throw new ContainerFormatError('split table too short');
			const split = bits.get(at++);
			if (!split) {
				first.push(pixel * 4 ** (CELL_LEVEL - depth));
				level.push(depth);
				return;
			}
			if (depth === CELL_LEVEL) throw new ContainerFormatError('a cell cannot split');
			for (let k = 0; k < 4; k++) visit(depth + 1, 4 * pixel + k);
		};
		for (let root = 0; root < ROOTS; root++) visit(0, root);
		if (at !== bits.length) {
			throw new ContainerFormatError(`split table has ${bits.length} bits, the tree ${at}`);
		}
		return new SplitTree(Uint32Array.from(first), Uint8Array.from(level));
	}

	get leaves(): number {
		return this.first.length;
	}

	/** The tile that holds `cell`. */
	tileOf(cell: number): TileKey {
		const first = this.first;
		let lo = 0;
		let hi = first.length - 1;
		while (lo < hi) {
			const mid = (lo + hi + 1) >> 1;
			if (first[mid] <= cell) lo = mid;
			else hi = mid - 1;
		}
		const level = this.level[lo];
		return { level, pixel: first[lo] / 4 ** (CELL_LEVEL - level) };
	}
}

/** Row of `id` in an ascending ID column, or -1. */
export function findId(ids: Float64Array, id: number): number {
	let lo = 0;
	let hi = ids.length - 1;
	while (lo <= hi) {
		const mid = (lo + hi) >>> 1;
		const at = ids[mid];
		if (at === id) return mid;
		if (at < id) lo = mid + 1;
		else hi = mid - 1;
	}
	return -1;
}
