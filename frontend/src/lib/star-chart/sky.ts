/**
 * The sky behind a star chart. A source paints the sky of a frame, once. The
 * chart knows nothing else of where the picture comes from.
 */

import { planeHalf, type ChartFrame } from './frame';

export interface Pixels {
	/** RGBA, rows from the top. */
	data: Uint8ClampedArray<ArrayBuffer>;
	width: number;
	height: number;
}

export interface SkySource {
	/**
	 * The sky of `frame` as a picture of `width` by `height` pixels, which has
	 * the aspect of the frame. Null when the source has no sky yet. `signal`
	 * ends the work of a paint that the chart no longer wants.
	 */
	paint(
		frame: ChartFrame,
		width: number,
		height: number,
		signal?: AbortSignal
	): Promise<Pixels | null>;
	/** Hear when a new paint gives another picture. Returns the unsubscribe. */
	onChange(listener: () => void): () => void;
	/** Radians of sky in one pixel of the source at its finest. Null while the
	 *  source has no sky. */
	finest?(): number | null;
	/** Whether a paint of this picture shows less than a sky whose pixel is
	 *  `step` radians. */
	yields?(frame: ChartFrame, width: number, height: number, step: number): boolean;
}

/** The sky of the charts on a page. Each chart hears of its own picture only. */
export interface ChartSky {
	/** As {@link SkySource.paint}. A picture shown while a better one is on its
	 *  way can be smaller than asked. */
	paint: SkySource['paint'];
	/** Hear when a new paint of `frame` gives a better picture. Returns the unsubscribe. */
	watch(frame: ChartFrame, listener: () => void): () => void;
}

/** Pixels of the painted sky per CSS pixel, at most. */
export const PAINT_RATIO = 2;
/** The most pixels of one painted sky. It caps the memory and the readback
 *  of a paint on a large screen. */
export const MAX_PAINT_PIXELS = 6_000_000;

/** Painted pixels per CSS pixel for a frame of this size: `wanted` up to
 *  {@link PAINT_RATIO}, or less for a frame past {@link MAX_PAINT_PIXELS}. */
export function paintRatio(width: number, height: number, wanted = PAINT_RATIO): number {
	return Math.min(wanted, PAINT_RATIO, Math.sqrt(MAX_PAINT_PIXELS / (width * height)));
}

/** Taps on each side of a pixel that holds `texels` of the source: one per
 *  texel, up to `limit`. */
export function tapsPerSide(texels: number, limit: number): number {
	return Math.min(Math.max(Math.ceil(texels), 1), limit);
}

/** How much of a pixel's brightest tap it keeps over its mean. A mean alone
 *  loses the stars of a small chart, since a star is a few pixels of the map. */
export const PEAK_SHARE = 0.7;

/** How far the faint sky is raised. The Milky Way stays under the stars. */
const EXPOSURE = 5;

/**
 * GLSL of a source that draws with a shader. `chartRay` gives the ICRS
 * direction of a point of the frame, from the uniforms of {@link rayUniforms}.
 * `chartTone` takes the light of the star map, 0 to 1, to the display. Each
 * source uses both, so that all sources draw the same sky.
 */
export const CHART_GLSL = /* glsl */ `
uniform vec3 uRight;
uniform vec3 uUp;
uniform vec3 uForward;
uniform vec2 uHalf;

// uv: (0, 0) at the top left of the frame.
vec3 chartRay(vec2 uv) {
	vec2 p = vec2(uv.x * 2.0 - 1.0, 1.0 - uv.y * 2.0) * uHalf;
	float r2 = dot(p, p);
	vec3 d = vec3(4.0 * p, 4.0 - r2) / (4.0 + r2);
	return d.x * uRight + d.y * uUp + d.z * uForward;
}

vec3 chartTone(vec3 light) {
	vec3 held = light * ${EXPOSURE.toFixed(1)} / (1.0 + light * ${EXPOSURE.toFixed(1)});
	vec3 lifted = 1.0 - exp(-held * 2.2);
	return pow(lifted, vec3(1.0 / 2.2));
}
`;

/** The frame as the uniforms of {@link CHART_GLSL}. */
export function rayUniforms(frame: ChartFrame): {
	uRight: readonly number[];
	uUp: readonly number[];
	uForward: readonly number[];
	uHalf: readonly number[];
} {
	return {
		uRight: frame.right,
		uUp: frame.up,
		uForward: frame.forward,
		uHalf: planeHalf(frame)
	};
}

/** How much of the brightest of its four pixels a pixel of a half-size
 *  picture keeps over their mean. */
export const HALF_PEAK_SHARE = 0.5;

/** A picture at half the size. A mean alone dims its stars. */
export function halved(pixels: Pixels): Pixels {
	const width = pixels.width >> 1;
	const height = pixels.height >> 1;
	const from = pixels.data;
	const data = new Uint8ClampedArray(width * height * 4).fill(255);
	const row = pixels.width * 4;
	for (let y = 0; y < height; y++) {
		for (let x = 0; x < width; x++) {
			const at = y * 2 * row + x * 8;
			const to = (y * width + x) * 4;
			for (let c = 0; c < 3; c++) {
				const a = from[at + c];
				const b = from[at + 4 + c];
				const d = from[at + row + c];
				const e = from[at + row + 4 + c];
				const mean = (a + b + d + e) / 4;
				data[to + c] = mean + (Math.max(a, b, d, e) - mean) * HALF_PEAK_SHARE;
			}
		}
	}
	return { data, width, height };
}

function luma(pixels: Pixels, x: number, y: number): number {
	const i = (y * pixels.width + x) * 4;
	return 0.2126 * pixels.data[i] + 0.7152 * pixels.data[i + 1] + 0.0722 * pixels.data[i + 2];
}

/**
 * How bright a star is in the painted sky: its light over the sky around it,
 * summed on a disc of `radius` pixels at (x, y). 0 for a point off the picture.
 * The names of a chart go to the stars that the reader sees best.
 */
export function paintedFlux(pixels: Pixels, x: number, y: number, radius: number): number {
	const cx = Math.round(x);
	const cy = Math.round(y);
	const reach = Math.ceil(radius * 2);
	if (cx < reach || cy < reach || cx >= pixels.width - reach || cy >= pixels.height - reach)
		return 0;
	let disc = 0;
	let discCount = 0;
	let ring = 0;
	let ringCount = 0;
	for (let dy = -reach; dy <= reach; dy++) {
		for (let dx = -reach; dx <= reach; dx++) {
			const distance = Math.hypot(dx, dy);
			if (distance <= radius) {
				disc += luma(pixels, cx + dx, cy + dy);
				discCount++;
			} else if (distance > reach - 1 && distance <= reach) {
				ring += luma(pixels, cx + dx, cy + dy);
				ringCount++;
			}
		}
	}
	return Math.max(disc - (ring / Math.max(ringCount, 1)) * discCount, 0);
}
