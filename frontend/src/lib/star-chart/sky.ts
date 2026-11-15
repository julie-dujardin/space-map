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
	 * the aspect of the frame. Null when the source has no sky yet.
	 */
	paint(frame: ChartFrame, width: number, height: number): Promise<Pixels | null>;
	/** Hear when a new paint gives another picture. Returns the unsubscribe. */
	onChange(listener: () => void): () => void;
}

/**
 * GLSL of a source that draws with a shader. `chartRay` gives the ICRS
 * direction of a point of the frame, from the uniforms of {@link rayUniforms}.
 * `chartTone` takes linear sky light to the display. Each source uses both, so
 * that all sources draw the same sky.
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

vec3 chartTone(vec3 linear) {
	vec3 lifted = 1.0 - exp(-linear * ${(2.2).toFixed(1)});
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
