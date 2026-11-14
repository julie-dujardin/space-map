/**
 * Whether this browser keeps the colour under a clear pixel of a decoded tile.
 *
 * A pyramid can hold a mask in the alpha of its tiles. A browser that
 * premultiplies the decoded tile loses the colour where the mask is clear.
 * Such a browser loads the tiles without their alpha, and the body keeps its
 * whole-globe mask.
 */

/** A 1×1 WebP encoded as the tiles are, lossy with an alpha chunk: RGB 201,
 *  100, 48 under alpha 0. */
const CLEAR_PIXEL =
	'UklGRlYAAABXRUJQVlA4WAoAAAAQAAAAAAAAAAAAQUxQSAIAAAAQAFZQOCAuAAAA8AEAnQEqAQABAAFAJiWgAnS6AfgABMgAAP6uF/82BAzQ+mD/0mzxNnibPjmAAA==';

let kept: boolean | undefined;
let probe: Promise<boolean> | undefined;

/** The result of {@link probeTileAlpha}. False until it has run. */
export function tileAlphaKept(): boolean {
	return kept === true;
}

/** Decode the probe pixel the way tiles are decoded, upload it, and read it back. */
export function probeTileAlpha(): Promise<boolean> {
	probe ??= readBack().then(
		(ok) => (kept = ok),
		() => (kept = false)
	);
	return probe;
}

async function readBack(): Promise<boolean> {
	const bytes = Uint8Array.from(atob(CLEAR_PIXEL), (c) => c.charCodeAt(0));
	const bitmap = await createImageBitmap(new Blob([bytes], { type: 'image/webp' }), {
		premultiplyAlpha: 'none',
		colorSpaceConversion: 'none'
	});
	const gl = document.createElement('canvas').getContext('webgl2');
	try {
		if (!gl) return false;
		const texture = gl.createTexture();
		gl.bindTexture(gl.TEXTURE_2D, texture);
		gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
		gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
		gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, bitmap);
		gl.bindFramebuffer(gl.FRAMEBUFFER, gl.createFramebuffer());
		gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);
		const pixel = new Uint8Array(4);
		gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
		return pixel[0] > 150 && pixel[3] === 0;
	} finally {
		bitmap.close();
		gl?.getExtension('WEBGL_lose_context')?.loseContext();
	}
}
