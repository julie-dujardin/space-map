/** A canvas for a sky painter of its own. */

/** A canvas with a WebGL 2 context, off the page where the browser can: some
 *  browsers have an OffscreenCanvas with no WebGL 2. Null on a device with no
 *  WebGL 2. */
export function webgl2Canvas(
	attributes: WebGLContextAttributes
): { canvas: OffscreenCanvas | HTMLCanvasElement; gl: WebGL2RenderingContext } | null {
	const open = (canvas: OffscreenCanvas | HTMLCanvasElement): WebGL2RenderingContext | null =>
		canvas.getContext('webgl2', attributes) as WebGL2RenderingContext | null;
	if (typeof OffscreenCanvas !== 'undefined') {
		const canvas = new OffscreenCanvas(1, 1);
		const gl = open(canvas);
		if (gl) return { canvas, gl };
	}
	const canvas = document.createElement('canvas');
	const gl = open(canvas);
	return gl ? { canvas, gl } : null;
}
