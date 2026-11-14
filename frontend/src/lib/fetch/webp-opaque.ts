/**
 * A lossy WebP without its alpha. A 2D canvas, and some decoders, keep no
 * colour under a clear pixel. A tile whose alpha holds a mask is made opaque
 * before such a decode.
 */

const RIFF_HEADER = 12;
const CHUNK_HEADER = 8;

function fourcc(bytes: Uint8Array, at: number): string {
	return String.fromCharCode(bytes[at], bytes[at + 1], bytes[at + 2], bytes[at + 3]);
}

/** The file with its `VP8 ` chunk alone, in the simple format. A file with no
 *  such chunk (lossless, or already simple) comes back as it is. */
export function opaqueWebp(buffer: ArrayBuffer): ArrayBuffer {
	const bytes = new Uint8Array(buffer);
	if (bytes.length < RIFF_HEADER + CHUNK_HEADER || fourcc(bytes, 12) !== 'VP8X') return buffer;
	const view = new DataView(buffer);
	let at = RIFF_HEADER;
	while (at + CHUNK_HEADER <= bytes.length) {
		const size = view.getUint32(at + 4, true);
		const padded = size + (size & 1);
		if (fourcc(bytes, at) === 'VP8 ') {
			const out = new Uint8Array(RIFF_HEADER + CHUNK_HEADER + padded);
			out.set(bytes.subarray(0, RIFF_HEADER));
			new DataView(out.buffer).setUint32(4, out.length - 8, true);
			out.set(bytes.subarray(at, at + CHUNK_HEADER + padded), RIFF_HEADER);
			return out.buffer;
		}
		at += CHUNK_HEADER + padded;
	}
	return buffer;
}

/** The body of a WebP response, without its alpha. */
export async function opaqueWebpBlob(response: Response): Promise<Blob> {
	return new Blob([opaqueWebp(await response.arrayBuffer())], { type: 'image/webp' });
}
