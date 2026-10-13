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

import { CAP_EDGE, MAP, NORTH, chartColumns, type Chart } from '$lib/scene/lod/tile-window';
import type { Projection } from './projection';
import { chartFraction } from './tile-plan';
import type { Viewport } from './view';

/** A texture read back into memory so it can be sampled pixel by pixel. */
export interface RasterImage {
	width: number;
	height: number;
	/** RGBA, four bytes per pixel, rows from north to south. */
	data: Uint8ClampedArray;
}

/**
 * A window of tile pixels: a rectangle of one level of one chart
 * (docs/export-format/tiles.md). A map column is not wrapped, so a window can
 * continue past the ±180° meridian.
 */
export interface DetailWindow {
	chart: Chart;
	level: number;
	tileSize: number;
	/** North-west pixel of the window on its chart. */
	x0: number;
	y0: number;
	width: number;
	height: number;
}

/** A window that a resampled map reads. */
export interface DetailRaster extends DetailWindow {
	/** RGBA, rows from the top. Alpha is 0 where no tile is in. */
	data: Uint8ClampedArray;
}

/** A window that an equirectangular map draws. Map chart only. */
export interface DetailCanvas extends DetailWindow {
	canvas: CanvasImageSource;
}

/** One picture in the stack, and how it goes on top of what is under it. */
export interface RasterLayerDraw {
	image: RasterImage;
	opacity: number;
	/** `normal` covers what is beneath by its alpha; `add` only ever brightens,
	 *  which is what a lights-at-night or an aurora overlay wants. */
	blend: 'normal' | 'add';
	/** Tile windows over the picture, finest first. */
	detail?: readonly DetailRaster[];
}

/** Where each pixel of a frame falls on a chart, as offsets from `ref`. */
interface ChartOffsets {
	refX: number;
	refY: number;
	x: Float32Array;
	y: Float32Array;
}

/** Pixels between two exact cap coordinates of a lookup. */
const CAP_GRID = 8;

/** Pixels across a whole chart at the level of `win`. */
function chartWidth(win: DetailWindow): number {
	return chartColumns(win.chart, win.level) * win.tileSize;
}

/** A picture's own pixel size. A source that does not say — an SVG image, whose
 *  size is whatever it is drawn at — has none to report. */
function sourceSize(source: CanvasImageSource): [number, number] | null {
	const width = 'width' in source ? source.width : source.codedWidth;
	const height = 'height' in source ? source.height : source.codedHeight;
	if (typeof width !== 'number' || typeof height !== 'number' || !width || !height) return null;
	return [width, height];
}

/**
 * Read a decoded picture back as pixels, shrinking it to `maxWidth` first.
 *
 * The shrink is the browser's, which filters as it goes; sampling a 16k-wide
 * texture one pixel at a time would otherwise alias badly wherever the map is
 * drawn smaller than its source.
 */
export function imageToRaster(source: CanvasImageSource, maxWidth: number): RasterImage | null {
	// A texture that does not know its own size is taken to be a world map at the
	// size asked for, which is the shape every map in the export has.
	const [sourceWidth, sourceHeight] = sourceSize(source) ?? [maxWidth, maxWidth / 2];
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
 * Where each destination pixel reads from, as texture coordinates.
 *
 * The coordinates are offsets from the middle of the frame. A float then has
 * the precision for the deepest tile level, where the whole texture is 2²⁷
 * pixels wide.
 */
export class InverseLookup {
	readonly width: number;
	readonly height: number;
	/** The middle of the frame: across the texture from −180° of longitude and
	 *  down it from the north pole, as fractions. */
	readonly refU: number;
	readonly refV: number;
	/** Across the texture from `refU`, the short way around. */
	readonly u: Float32Array;
	/** Down the texture from `refV`. */
	readonly v: Float32Array;
	/** 1 where the pixel is on the map at all, 0 where it falls outside. */
	readonly inside: Uint8Array;
	private readonly caps = new Map<Chart, ChartOffsets>();

	constructor(viewport: Viewport, width: number, height: number) {
		this.width = width;
		this.height = height;
		const count = width * height;
		this.u = new Float32Array(count);
		this.v = new Float32Array(count);
		this.inside = new Uint8Array(count);
		const { projection } = viewport;
		const middle = projection.inverse(viewport.view.centerX, viewport.view.centerY);
		[this.refU, this.refV] = middle ? chartFraction(MAP, middle[0], middle[1]) : [0.5, 0.5];
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
		const { width, refU } = this;
		const v = (90 - line.lat) / 180 - this.refV;
		const { minX, maxX } = projection.extent;
		const worldWidth = maxX - minX;
		// A cyclic projection's inverse accepts any abscissa, since panning past
		// the seam has to keep working. Where the map is not drawn again — a
		// pointed world, or a frame wider than one copy of it — that would paint a
		// second world beside the first, so the plane is bounded instead.
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
			const turns = (x * line.lonPerX + projection.centerLon + 180) / 360 - refU;
			const i = row + px;
			this.u[i] = turns - Math.round(turns);
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
			const turns = (place[0] + 180) / 360 - this.refU;
			this.u[i] = turns - Math.round(turns);
			this.v[i] = (90 - place[1]) / 180 - this.refV;
			this.inside[i] = 1;
		}
	}

	/** Where each pixel falls on `chart`. The offsets of a cap are made on
	 *  first use. */
	offsets(chart: Chart): ChartOffsets {
		if (chart === MAP) return { refX: this.refU, refY: this.refV, x: this.u, y: this.v };
		let cap = this.caps.get(chart);
		if (!cap) {
			cap = this.capOffsets(chart);
			this.caps.set(chart, cap);
		}
		return cap;
	}

	/**
	 * The offsets of a cap. They are exact on a grid of pixels and linear
	 * between them: a cap coordinate changes slowly across a frame, and the
	 * exact value costs three trigonometric functions for each pixel.
	 */
	private capOffsets(chart: Chart): ChartOffsets {
		const { u, v, inside, refU, refV, width, height } = this;
		const side = chart === NORTH ? 1 : -1;
		const [refX, refY] = chartFraction(chart, refU * 360 - 180, 90 - refV * 180);
		const x = new Float32Array(u.length);
		const y = new Float32Array(u.length);
		const exact = (i: number): void => {
			const fromPole = side > 0 ? refV + v[i] : 1 - refV - v[i];
			const radius = (0.5 * Math.tan((fromPole * Math.PI) / 2)) / CAP_EDGE;
			const lon = (refU + u[i]) * 2 * Math.PI - Math.PI;
			x[i] = 0.5 + radius * Math.cos(lon) - refX;
			y[i] = 0.5 - side * radius * Math.sin(lon) - refY;
		};
		const columns = gridLines(width);
		const rows = gridLines(height);
		// A frame of one pixel across has no cell.
		if (columns.length < 2 || rows.length < 2) {
			for (let i = 0; i < u.length; i++) if (inside[i]) exact(i);
			return { refX, refY, x, y };
		}
		for (const py of rows) {
			for (const px of columns) if (inside[py * width + px]) exact(py * width + px);
		}
		for (let r = 0; r < rows.length - 1; r++) {
			const top = rows[r];
			const bottom = rows[r + 1];
			// The last row and column of a cell are the first of the next one.
			const lastRow = r === rows.length - 2 ? bottom : bottom - 1;
			for (let c = 0; c < columns.length - 1; c++) {
				const left = columns[c];
				const right = columns[c + 1];
				const lastColumn = c === columns.length - 2 ? right : right - 1;
				const nw = top * width + left;
				const ne = top * width + right;
				const sw = bottom * width + left;
				const se = bottom * width + right;
				// A cell at the edge of the world has no value at one of its corners.
				if (!(inside[nw] && inside[ne] && inside[sw] && inside[se])) {
					for (let py = top; py <= lastRow; py++) {
						for (let i = py * width + left; i <= py * width + lastColumn; i++) {
							if (inside[i]) exact(i);
						}
					}
					continue;
				}
				for (let py = top; py <= lastRow; py++) {
					const fy = (py - top) / (bottom - top);
					let atX = x[nw] + fy * (x[sw] - x[nw]);
					let atY = y[nw] + fy * (y[sw] - y[nw]);
					const stepX = (x[ne] + fy * (x[se] - x[ne]) - atX) / (right - left);
					const stepY = (y[ne] + fy * (y[se] - y[ne]) - atY) / (right - left);
					// The corners keep their exact values.
					const skip = py === top || py === bottom;
					for (let px = left; px <= lastColumn; px++) {
						if (!(skip && (px === left || px === right))) {
							x[py * width + px] = atX;
							y[py * width + px] = atY;
						}
						atX += stepX;
						atY += stepY;
					}
				}
			}
		}
		return { refX, refY, x, y };
	}
}

/** The pixels of a line of `length` that hold an exact cap coordinate: each
 *  `CAP_GRID`-th one, and the last. */
function gridLines(length: number): number[] {
	const lines: number[] = [];
	for (let at = 0; at < length - 1; at += CAP_GRID) lines.push(at);
	lines.push(length - 1);
	return lines;
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
	const { width, height, u, v, inside, refU, refV } = lookup;
	const count = width * height;

	for (const layer of layers) {
		const { image, opacity, blend } = layer;
		if (opacity <= 0) continue;
		const base = image.data;
		const sw = image.width;
		const sh = image.height;
		const add = blend === 'add';
		const windows = (layer.detail ?? []).map((win) => {
			const offsets = lookup.offsets(win.chart);
			const across = chartWidth(win);
			const down = win.chart === MAP ? across / 2 : across;
			let left = offsets.refX * across - win.x0;
			// The turn of the globe that puts the window at the middle of the frame.
			if (win.chart === MAP) left -= across * Math.round((left - win.width / 2) / across);
			return {
				xs: offsets.x,
				ys: offsets.y,
				left,
				top: offsets.refY * down - win.y0,
				across,
				down,
				width: win.width,
				height: win.height,
				data: win.data
			};
		});

		for (let i = 0; i < count; i++) {
			if (!inside[i]) continue;
			let src = base;
			let s = -1;
			for (let k = 0; k < windows.length; k++) {
				const win = windows[k];
				// Written so that a coordinate that is not a number fails the test.
				const tx = win.left + win.xs[i] * win.across;
				if (!(tx >= 0 && tx < win.width)) continue;
				const ty = win.top + win.ys[i] * win.down;
				if (!(ty >= 0 && ty < win.height)) continue;
				const t = ((ty | 0) * win.width + (tx | 0)) * 4;
				if (win.data[t + 3] === 0) continue;
				src = win.data;
				s = t;
				break;
			}
			if (s < 0) {
				// Nearest neighbour: the source was already filtered down to about the
				// drawn size, so interpolating here would only blur it again.
				let across = refU + u[i];
				across -= Math.floor(across);
				let sx = Math.floor(across * sw);
				let sy = Math.floor((refV + v[i]) * sh);
				// The seam wraps; the poles clamp.
				sx = sx < 0 ? sx + sw : sx >= sw ? sx - sw : sx;
				sy = sy < 0 ? 0 : sy >= sh ? sh - 1 : sy;
				s = (sy * sw + sx) * 4;
			}
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
 * texture is already in, so the whole world is a rectangle and the picture goes
 * down as it is.
 *
 * It goes down as a repeating pattern rather than as copies drawn side by side.
 * A copy is filtered against its own edge, so two of them meet in a column that
 * belongs to neither: the picture flattens for a pixel and then steps, which
 * reads as a hairline down the seam. A pattern's filter wraps instead, and the
 * seam comes out as smooth as anywhere else on the map.
 */
export function drawEquirect(
	ctx: CanvasRenderingContext2D,
	viewport: Viewport,
	layers: readonly {
		image: CanvasImageSource;
		opacity: number;
		blend: 'normal' | 'add';
		/** Tile windows over the picture, finest first. */
		detail?: readonly DetailCanvas[];
	}[]
): void {
	const { minX, maxX, minY, maxY } = viewport.projection.extent;
	// The texture always starts at −180°, while the plane starts at the central
	// meridian minus 180°: the pattern is laid down shifted by that difference,
	// and its own repeat carries whatever the shift pushed off the far edge.
	const meridian = (viewport.projection.centerLon * Math.PI) / 180;
	const [left, top] = viewport.toScreen(minX - meridian, maxY);
	const [right, bottom] = viewport.toScreen(maxX - meridian, minY);
	// Where the pattern is allowed to show: right across the canvas while the map
	// carries on either side of itself, and otherwise the world's own width, so
	// the repeat that rotates the meridian does not spill past the map's edge.
	const from = viewport.repeatsHorizontally ? 0 : viewport.toScreen(minX, maxY)[0];
	const to = viewport.repeatsHorizontally ? ctx.canvas.width : viewport.toScreen(maxX, maxY)[0];

	const paint = (
		target: CanvasRenderingContext2D,
		layer: (typeof layers)[number],
		size: [number, number]
	): void => {
		const pattern = target.createPattern(layer.image, 'repeat-x');
		if (!pattern) return;
		pattern.setTransform(
			new DOMMatrix()
				.translateSelf(left, top)
				.scaleSelf((right - left) / size[0], (bottom - top) / size[1])
		);
		// Saved and restored, so the pattern is not left on the context holding a
		// picture the next draw has no use for.
		target.save();
		target.imageSmoothingEnabled = true;
		target.imageSmoothingQuality = 'high';
		target.fillStyle = pattern;
		target.fillRect(from, top, to - from, bottom - top);
		const detail = layer.detail ?? [];
		if (detail.length) {
			target.beginPath();
			target.rect(from, top, to - from, bottom - top);
			target.clip();
		}
		for (let k = detail.length - 1; k >= 0; k--) {
			const win = detail[k];
			const scale = (right - left) / chartWidth(win);
			let x = left + win.x0 * scale;
			// The copy of the world that puts the window in the frame.
			const middle = x + (win.width * scale) / 2;
			x += (right - left) * Math.round((target.canvas.width / 2 - middle) / (right - left));
			target.drawImage(win.canvas, x, top + win.y0 * scale, win.width * scale, win.height * scale);
		}
		target.restore();
	};

	ctx.save();
	for (const layer of layers) {
		if (layer.opacity <= 0) continue;
		const size = sourceSize(layer.image);
		if (!size) continue;
		ctx.globalAlpha = layer.opacity;
		ctx.globalCompositeOperation = layer.blend === 'add' ? 'lighter' : 'source-over';
		// A window covers the picture under it. On a layer that lets the map
		// below show, the two are joined first, or that picture shows twice.
		const joined = layer.detail?.length && (layer.opacity < 1 || layer.blend === 'add');
		const scratch = joined ? scratchContext(ctx.canvas.width, ctx.canvas.height) : null;
		if (scratch) {
			paint(scratch, layer, size);
			ctx.drawImage(scratch.canvas, 0, 0);
		} else {
			paint(ctx, layer, size);
		}
	}
	ctx.restore();
}

let scratch: CanvasRenderingContext2D | null = null;

/** A cleared canvas of this size, shared by all maps. */
function scratchContext(width: number, height: number): CanvasRenderingContext2D | null {
	scratch ??= document.createElement('canvas').getContext('2d');
	if (!scratch) return null;
	if (scratch.canvas.width !== width || scratch.canvas.height !== height) {
		scratch.canvas.width = width;
		scratch.canvas.height = height;
	} else {
		scratch.clearRect(0, 0, width, height);
	}
	return scratch;
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
