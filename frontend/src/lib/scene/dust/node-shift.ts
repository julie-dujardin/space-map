/**
 * One change of column for a whole node, for a device with no sky map. A node's
 * stars share it, so the shift is a mean over a few of them, taken in flux. It
 * keeps the node's total light.
 */

import { K_G, MAG_LN, decodeBound } from './extinction';
import { columnBetween, type NestLevel } from './nest';
import type { Vec3 } from './octahedral';

/** Stars of a node that stand for all of them. */
const NODE_SAMPLES = 8;
const SUN: Vec3 = [0, 0, 0];

/** The sample stars of a node, with their columns from the Sun. */
export interface NodeSample {
	places: Vec3[];
	sun: Float64Array;
	/** The most A0 each star can gain (`dustBound`). */
	bound: Float64Array;
}

/**
 * Evenly spaced rows of a node. `offsets` holds x, y, z per star from `centre`,
 * on tree axes, and `bounds` the byte of each star's `dustBound`. `toNest` takes
 * tree axes to nest axes.
 */
export function sampleNode(
	levels: readonly NestLevel[],
	offsets: Float32Array,
	bounds: Uint8Array,
	centre: readonly [number, number, number],
	toNest: (v: readonly [number, number, number]) => Vec3
): NodeSample {
	const rows = offsets.length / 3;
	const count = Math.min(NODE_SAMPLES, rows);
	const places: Vec3[] = [];
	const bound = new Float64Array(count);
	for (let k = 0; k < count; k++) {
		const row = Math.floor(((k + 0.5) * rows) / count);
		bound[k] = decodeBound(bounds[row]);
		places.push(
			toNest([
				centre[0] + offsets[3 * row],
				centre[1] + offsets[3 * row + 1],
				centre[2] + offsets[3 * row + 2]
			])
		);
	}
	const sun = new Float64Array(places.map((place) => columnBetween(levels, SUN, place)));
	return { places, sun, bound };
}

/** The change of column (mag at 550 nm) from `origin`, against the view from
 *  the Sun. A node with no stars has none. */
export function nodeShift(levels: readonly NestLevel[], sample: NodeSample, origin: Vec3): number {
	const { places, sun, bound } = sample;
	if (places.length === 0) return 0;
	let flux = 0;
	for (let k = 0; k < places.length; k++) {
		const change = Math.max(columnBetween(levels, origin, places[k]) - sun[k], -bound[k]);
		flux += Math.exp(-MAG_LN * K_G * change);
	}
	return -Math.log(flux / places.length) / (MAG_LN * K_G);
}
