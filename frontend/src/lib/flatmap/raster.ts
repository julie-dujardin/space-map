/**
 * Redrawing an equirectangular texture in another projection. Every map
 * texture in the export is stored the one way — longitude across, latitude
 * down — so a projection change is a resampling: walk the destination pixels,
 * ask the projection where each one falls on the globe, and read the texture
 * there.
 *
 * The walk is the expensive part and it depends only on the projection and the
 * view, not on the pictures, so it is kept as a lookup table and shared by
 * every layer drawn through it.
 */

import type { Projection } from './projection';
import type { Viewport } from './view';

/** A texture read back into memory so it can be sampled pixel by pixel. */
export interface RasterImage {
	width: number;
	height: number;
	/** RGBA, four bytes per pixel, rows from north to south. */
	data: Uint8ClampedArray;
}

/** One picture in the stack, and how it goes on top of what is under it. */
export interface RasterLayerDraw {
	image: RasterImage;
	opacity: number;
	/** `normal` covers what is beneath by its alpha; `add` only ever brightens,
	 *  which is what a lights-at-night or an aurora overlay wants. */
	blend: 'normal' | 'add';
}

/**
 * Read a decoded picture back as pixels, shrinking it to `maxWidth` first.
 *
 * The shrink is the browser's, which filters as it goes; sampling a 16k-wide
 * texture one pixel at a time would otherwise alias badly wherever the map is
 * drawn smaller than its source.
 */
export function imageToRaster(source: CanvasImageSource, maxWidth: number): RasterImage | null {
	const sourceWidth =
		'width' in source && typeof source.width === 'number' ? source.width : maxWidth;
	const sourceHeight =
		'height' in source && typeof source.height === 'number' ? source.height : maxWidth / 2;
	if (!sourceWidth || !sourceHeight) return null;
	const width = Math.max(2, Math.min(sourceWidth, Math.round(maxWidth)));
	const height = Math.max(1, Math.round((width * sourceHeight) / sourceWidth));
	const canvas = document.createElement('canvas');
	canvas.width = width;
	canvas.height = height;
	const ctx = canvas.getContext('2d', { willReadFrequently: true });
	if (!ctx) return null;
	ctx.imageSmoothingEnabled = true;
	ctx.imageSmoothingQuality = 'high';
	ctx.drawImage(source, 0, 0, width, height);
	try {
		const { data } = ctx.getImageData(0, 0, width, height);
		return { width, height, data };
	} catch {
		// A texture from another origin without CORS taints the canvas. Nothing
		// in the export is served that way, but a host's own layer might be.
		return null;
	}
}

/**
 * Where each destination pixel reads from, as texture coordinates in 0…1.
 * Held as one flat pair of arrays rather than objects: this is the hot loop,
 * and at a megapixel the allocation alone would dominate.
 */
export class InverseLookup {
	readonly width: number;
	readonly height: number;
	/** Across the texture, 0 at −180° of longitude. */
	readonly u: Float32Array;
	/** Down the texture, 0 at the north pole. */
	readonly v: Float32Array;
	/** 1 where the pixel is on the map at all, 0 where it falls outside. */
	readonly inside: Uint8Array;

	constructor(viewport: Viewport, width: number, height: number) {
		this.width = width;
		this.height = height;
		const count = width * height;
		this.u = new Float32Array(count);
		this.v = new Float32Array(count);
		this.inside = new Uint8Array(count);
		const { projection } = viewport;
		// The screen-to-plane step is written out rather than called: it is an
		// affine map, and at a megapixel the pair it would return per pixel costs
		// more in allocation than the whole walk does in arithmetic.
		const step = 1 / viewport.scale;
		const x0 = viewport.view.centerX - (viewport.width / 2) * step;
		const y0 = viewport.view.centerY + (viewport.height / 2) * step;

		for (let py = 0; py < height; py++) {
			// Pixel centres, so the sampled point is the middle of the pixel rather
			// than its corner.
			const y = y0 - (py + 0.5) * step;
			const row = py * width;
			if (projection.rowInverse) this.fillRow(projection, row, y, x0, step, viewport);
			else this.walkRow(projection, row, y, x0, step);
		}
	}

	/**
	 * A row of a map whose every point lies on one parallel. The latitude and
	 * the scale of longitude are found once for the row; across it, longitude
	 * only has to be stepped, which is what makes changing projection cheap
	 * enough to do while the map is moving.
	 */
	private fillRow(
		projection: Projection,
		row: number,
		y: number,
		x0: number,
		step: number,
		viewport: Viewport
	): void {
		const line = projection.rowInverse!(y);
		if (!line) return;
		const { width } = this;
		const v = (90 - line.lat) / 180;
		const { minX, maxX } = projection.extent;
		const worldWidth = maxX - minX;
		// A cyclic projection accepts any abscissa, since panning past the seam
		// has to keep working. Where the world already fits, that would paint a
		// second copy of it beside the first, so the plane is bounded instead.
		const repeating = viewport.repeatsHorizontally;
		for (let px = 0; px < width; px++) {
			let x = x0 + (px + 0.5) * step;
			if (repeating) {
				// Folded back onto the one world before it is read, so a repeat
				// shows the map again rather than running off the end of it.
				x = ((((x - minX) % worldWidth) + worldWidth) % worldWidth) + minX;
			} else if (x < minX || x > maxX) {
				continue;
			}
			if (x < -line.maxAbsX || x > line.maxAbsX) continue;
			// Longitude wraps into 0…1 of the texture; the fractional part is the
			// wrap, and costs one floor rather than a modulo.
			const turns = (x * line.lonPerX + projection.centerLon + 180) / 360;
			const i = row + px;
			this.u[i] = turns - Math.floor(turns);
			this.v[i] = v;
			this.inside[i] = 1;
		}
	}

	/** A row of a map that shows a globe, where longitude and latitude both
	 *  depend on the whole point. Only the span inside the disc is walked —
	 *  the corners of the frame are never on the map. */
	private walkRow(projection: Projection, row: number, y: number, x0: number, step: number): void {
		const { width } = this;
		let from = 0;
		let to = width - 1;
		if (projection.azimuthal) {
			const radius = projection.extent.maxX;
			if (Math.abs(y) > radius) return;
			const half = Math.sqrt(radius * radius - y * y);
			from = Math.max(0, Math.ceil((-half - x0) / step - 0.5));
			to = Math.min(width - 1, Math.floor((half - x0) / step - 0.5));
		}
		for (let px = from; px <= to; px++) {
			const x = x0 + (px + 0.5) * step;
			const place = projection.inverse(x, y);
			if (!place) continue;
			const i = row + px;
			this.u[i] = (place[0] + 180) / 360;
			this.v[i] = (90 - place[1]) / 180;
			this.inside[i] = 1;
		}
	}
}

/**
 * Draw the stack through the lookup into `target`, which must be the lookup's
 * size. Layers are composited in the order given, first at the bottom.
 */
export function compositeLayers(
	lookup: InverseLookup,
	layers: readonly RasterLayerDraw[],
	target: ImageData
): void {
	const out = target.data;
	out.fill(0);
	const { width, height, u, v, inside } = lookup;
	const count = width * height;

	for (const layer of layers) {
		const { image, opacity, blend } = layer;
		if (opacity <= 0) continue;
		const src = image.data;
		const sw = image.width;
		const sh = image.height;
		const add = blend === 'add';

		for (let i = 0; i < count; i++) {
			if (!inside[i]) continue;
			// Nearest neighbour: the source was already filtered down to about the
			// drawn size, so interpolating here would only blur it again.
			let sx = Math.floor(u[i] * sw);
			let sy = Math.floor(v[i] * sh);
			// The seam wraps; the poles clamp.
			sx = sx < 0 ? sx + sw : sx >= sw ? sx - sw : sx;
			sy = sy < 0 ? 0 : sy >= sh ? sh - 1 : sy;
			const s = (sy * sw + sx) * 4;
			const alpha = (src[s + 3] / 255) * opacity;
			if (alpha <= 0) continue;
			const d = i * 4;

			if (add) {
				out[d] = Math.min(255, out[d] + src[s] * alpha);
				out[d + 1] = Math.min(255, out[d + 1] + src[s + 1] * alpha);
				out[d + 2] = Math.min(255, out[d + 2] + src[s + 2] * alpha);
				// Brightening only — an additive layer never makes the map more opaque
				// than the surface under it already was.
				continue;
			}

			const under = out[d + 3] / 255;
			const result = alpha + under * (1 - alpha);
			if (result <= 0) continue;
			// Source-over in straight alpha. Opaque source is the common case by
			// far, so it skips the blend entirely.
			if (alpha >= 1) {
				out[d] = src[s];
				out[d + 1] = src[s + 1];
				out[d + 2] = src[s + 2];
			} else {
				const k = under * (1 - alpha);
				out[d] = (src[s] * alpha + out[d] * k) / result;
				out[d + 1] = (src[s + 1] * alpha + out[d + 1] * k) / result;
				out[d + 2] = (src[s + 2] * alpha + out[d + 2] * k) / result;
			}
			out[d + 3] = result * 255;
		}
	}
}

/**
 * Draw the stack with the browser's own scaler, for the one projection where
 * the texture needs no resampling at all: equirectangular is the space the
 * texture is already in, so the whole world is a rectangle and the picture
 * goes down as it is. A cyclic map is drawn again either side of itself so a
 * view straddling the seam has no gap in it.
 */
export function drawEquirect(
	ctx: CanvasRenderingContext2D,
	viewport: Viewport,
	layers: readonly { image: CanvasImageSource; opacity: number; blend: 'normal' | 'add' }[]
): void {
	const { minX, maxX, minY, maxY } = viewport.projection.extent;
	// The texture always starts at −180°, while the plane starts at the central
	// meridian minus 180°: the strip is laid down shifted by that difference, and
	// the copies either side carry whatever the shift pushed off the far edge.
	const meridian = (viewport.projection.centerLon * Math.PI) / 180;
	const [left, top] = viewport.toScreen(minX - meridian, maxY);
	const [right, bottom] = viewport.toScreen(maxX - meridian, minY);
	const w = right - left;
	const h = bottom - top;
	const repeats = viewport.repeatsHorizontally || meridian !== 0 ? [-w, 0, w] : [0];
	ctx.imageSmoothingEnabled = true;
	ctx.imageSmoothingQuality = 'high';
	for (const layer of layers) {
		if (layer.opacity <= 0) continue;
		ctx.globalAlpha = layer.opacity;
		ctx.globalCompositeOperation = layer.blend === 'add' ? 'lighter' : 'source-over';
		for (const shift of repeats) {
			// Skip a copy that lands entirely outside the canvas.
			if (left + shift > ctx.canvas.width || left + shift + w < 0) continue;
			ctx.drawImage(layer.image, left + shift, top, w, h);
		}
	}
	ctx.globalAlpha = 1;
	ctx.globalCompositeOperation = 'source-over';
}

/**
 * Draw a stack into a canvas once, sizing its backing store to the viewport.
 *
 * The one-shot counterpart to what the live map does: no caching, no tiers, no
 * frames. For a still — a hero image, a thumbnail — where the projection
 * changes rarely and holding a lookup table between draws would cost more
 * memory than the redraw costs time.
 */
export function drawStill(
	canvas: HTMLCanvasElement,
	viewport: Viewport,
	layers: readonly { image: CanvasImageSource; opacity: number; blend: 'normal' | 'add' }[]
): void {
	const ctx = canvas.getContext('2d');
	if (!ctx) return;
	canvas.width = viewport.width;
	canvas.height = viewport.height;
	ctx.clearRect(0, 0, viewport.width, viewport.height);
	if (layers.length === 0) return;

	if (viewport.projection.id === 'equirectangular') {
		drawEquirect(ctx, viewport, layers);
		return;
	}

	// Twice the drawn width, so the sampling has detail to lose rather than
	// pixels to invent.
	const working = Math.min(4096, viewport.width * 2);
	const stack: RasterLayerDraw[] = [];
	for (const layer of layers) {
		const image = imageToRaster(layer.image, working);
		if (image) stack.push({ image, opacity: layer.opacity, blend: layer.blend });
	}
	if (stack.length === 0) return;
	const buffer = ctx.createImageData(viewport.width, viewport.height);
	compositeLayers(new InverseLookup(viewport, viewport.width, viewport.height), stack, buffer);
	ctx.putImageData(buffer, 0, 0);
}
