/**
 * Height tiles as numbers (docs/export-format/tiles.md): a tile holds a 16-bit
 * value per pixel, the high byte in red and the low byte in green.
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

/** The 16-bit height of each pixel of a decoded tile, north row first. */
export function heightValues(rgba: Uint8ClampedArray, size: number): Uint16Array {
	const out = new Uint16Array(size * size);
	for (let i = 0, src = 0; i < out.length; i++, src += 4) {
		out[i] = (rgba[src] << 8) | rgba[src + 1];
	}
	return out;
}
