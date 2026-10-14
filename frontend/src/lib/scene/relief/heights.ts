/**
 * Height tiles as numbers (docs/export-format/tiles.md): a tile holds a 16-bit
 * value per pixel, the high byte in red and the low byte in green. A tile of a
 * patch counts 256ths of that value's step in blue.
 */

/**
 * The two height bytes of each pixel of a decoded tile, south row first, as a
 * window texture stores them. `rgba` is `size` × `size`, north row first.
 */
export function packHeightBytes(rgba: Uint8ClampedArray, size: number): Uint8Array {
	const out = new Uint8Array(size * size * 2);
	for (let row = 0; row < size; row++) {
		let src = (size - 1 - row) * size * 4;
		let dst = row * size * 2;
		for (let x = 0; x < size; x++, src += 4, dst += 2) {
			out[dst] = rgba[src];
			out[dst + 1] = rgba[src + 1];
		}
	}
	return out;
}

/**
 * The height of each pixel of a decoded tile in 16-bit steps, with the part
 * of a step that a tile of a patch states, south row first: a window texture
 * of numbers.
 */
export function packHeightValues(rgba: Uint8ClampedArray, size: number): Float32Array {
	const out = new Float32Array(size * size);
	for (let row = 0; row < size; row++) {
		let src = (size - 1 - row) * size * 4;
		const end = (row + 1) * size;
		for (let dst = row * size; dst < end; dst++, src += 4) {
			out[dst] = ((rgba[src] << 8) | rgba[src + 1]) + rgba[src + 2] / 256;
		}
	}
	return out;
}

/** The height of each pixel of a decoded tile in 16-bit steps, north row
 *  first. `fine` keeps the part of a step that a tile of a patch states. */
export function heightValues(
	rgba: Uint8ClampedArray,
	size: number,
	fine: boolean
): Uint16Array | Float32Array {
	const out = fine ? new Float32Array(size * size) : new Uint16Array(size * size);
	for (let i = 0, src = 0; i < out.length; i++, src += 4) {
		const value = (rgba[src] << 8) | rgba[src + 1];
		out[i] = fine ? value + rgba[src + 2] / 256 : value;
	}
	return out;
}
