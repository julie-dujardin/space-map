/**
 * A host's line as the camera has it: cut where it leaves the view, and
 * measured along itself in pixels for its dashes. Dashes are counted on screen,
 * as the line's width is — a dash a thousand kilometres long is a dot from the
 * next planet and the whole line from low orbit.
 */

import { Vector3, type PerspectiveCamera } from 'three';

/** How far past the screen's edge a line is kept, in half-screens: far enough
 *  that its cut end never shows, near enough that its length in pixels stays a
 *  number a float32 can count dashes in. */
const REACH = 3;

const right = new Vector3();
const up = new Vector3();
const forward = new Vector3();

/** A dash and a gap in pixels from a pattern written as the flat map takes
 *  it, `"4 3"`; one number is both. Null for a solid line. */
export function parseDash(pattern: string | undefined): [number, number] | null {
	const [dash, gap = dash] = (pattern ?? '')
		.split(/[\s,]+/)
		.filter(Boolean)
		.map(Number);
	return dash > 0 && gap > 0 ? [dash, gap] : null;
}

/** Pixels per unit of sideways distance over depth. Sets the camera's axes
 *  from its pose rather than its matrices, which are a frame behind here. */
function aim(camera: PerspectiveCamera, viewportPx: number): number {
	right.set(1, 0, 0).applyQuaternion(camera.quaternion);
	up.set(0, 1, 0).applyQuaternion(camera.quaternion);
	forward.set(0, 0, -1).applyQuaternion(camera.quaternion);
	return viewportPx / (2 * Math.tan((camera.getEffectiveFOV() * Math.PI) / 360));
}

/** Point `i` of `points` on the camera's axes: right, up, and depth ahead. */
function view(points: Float32Array, i: number, camera: PerspectiveCamera, out: number[]): void {
	const x = points[i * 3] - camera.position.x;
	const y = points[i * 3 + 1] - camera.position.y;
	const z = points[i * 3 + 2] - camera.position.z;
	out[0] = x * right.x + y * right.y + z * right.z;
	out[1] = x * up.x + y * up.y + z * up.z;
	out[2] = x * forward.x + y * forward.y + z * forward.z;
}

/** Whether any of the line is behind the camera, where the line's shader has
 *  no screen position to widen it from. */
export function reachesBehind(
	points: Float32Array,
	count: number,
	camera: PerspectiveCamera
): boolean {
	forward.set(0, 0, -1).applyQuaternion(camera.quaternion);
	const { x, y, z } = camera.position;
	for (let i = 0; i < count; i++) {
		const depth =
			(points[i * 3] - x) * forward.x +
			(points[i * 3 + 1] - y) * forward.y +
			(points[i * 3 + 2] - z) * forward.z;
		if (depth < camera.near * 2) return true;
	}
	return false;
}

/**
 * How far along the line each of its points is, in screen pixels, into `out`.
 * `points` are in the frame the scene is drawn in. A point behind the camera
 * has no place on screen and adds nothing.
 */
export function screenLengths(
	points: Float32Array,
	count: number,
	camera: PerspectiveCamera,
	viewportPx: number,
	out: Float32Array
): void {
	const focal = aim(camera, viewportPx);
	const at = [0, 0, 0];
	let length = 0;
	let lastX = 0;
	let lastY = 0;
	let seen = false;
	for (let i = 0; i < count; i++) {
		view(points, i, camera, at);
		if (at[2] > camera.near) {
			const px = (at[0] / at[2]) * focal;
			const py = (at[1] / at[2]) * focal;
			if (seen) length += Math.hypot(px - lastX, py - lastY);
			lastX = px;
			lastY = py;
			seen = true;
		}
		out[i] = length;
	}
}

/**
 * The part of a line the camera can draw. A stretch out of view is left out,
 * and the pieces either side of it are joined by a stretch at no opacity, so
 * the whole is still one strip.
 */
export class SeenLine {
	points = new Float32Array(0);
	alphas = new Float32Array(0);
	/** Pixels along the line to each point. */
	lengths = new Float32Array(0);
	count = 0;

	private a = [0, 0, 0];
	private b = [0, 0, 0];

	see(
		points: Float32Array,
		alphas: Float32Array,
		count: number,
		camera: PerspectiveCamera,
		viewportPx: number
	): void {
		// Every stretch can come out as a piece of its own: two ends, and two
		// more to join it to the last.
		if (this.alphas.length < count * 4) {
			this.points = new Float32Array(count * 12);
			this.alphas = new Float32Array(count * 4);
			this.lengths = new Float32Array(count * 4);
		}
		this.count = 0;
		const focal = aim(camera, viewportPx);
		const halfW = (viewportPx * camera.aspect * REACH) / 2;
		const halfH = (viewportPx * REACH) / 2;
		const near = camera.near * 2;
		let { a, b } = this;
		let joined = false;
		let length = 0;
		let lastX = 0;
		let lastY = 0;
		if (count > 0) view(points, 0, camera, a);
		for (let i = 0; i + 1 < count; i++, [a, b] = [b, a]) {
			view(points, i + 1, camera, b);
			// The view is where each of these is positive, and each runs
			// straight along the stretch.
			let from = 0;
			let to = 1;
			for (let plane = 0; plane < 5 && from <= to; plane++) {
				const ga = edge(plane, a, focal, halfW, halfH, near);
				const gb = edge(plane, b, focal, halfW, halfH, near);
				if (ga < 0 && gb < 0) to = -1;
				else if (ga < 0) from = Math.max(from, ga / (ga - gb));
				else if (gb < 0) to = Math.min(to, ga / (ga - gb));
			}
			if (from > to) {
				joined = false;
				continue;
			}
			const depth = a[2] + (b[2] - a[2]) * from;
			const x = ((a[0] + (b[0] - a[0]) * from) / depth) * focal;
			const y = ((a[1] + (b[1] - a[1]) * from) / depth) * focal;
			if (!joined || from > 0) {
				if (this.count > 0) {
					this.copy(this.count - 1, 0);
					this.put(points, alphas, i, from, length, 0);
				}
				this.put(points, alphas, i, from, length, 1);
				lastX = x;
				lastY = y;
			}
			const endDepth = a[2] + (b[2] - a[2]) * to;
			const endX = ((a[0] + (b[0] - a[0]) * to) / endDepth) * focal;
			const endY = ((a[1] + (b[1] - a[1]) * to) / endDepth) * focal;
			length += Math.hypot(endX - lastX, endY - lastY);
			lastX = endX;
			lastY = endY;
			this.put(points, alphas, i, to, length, 1);
			joined = to === 1;
		}
	}

	/** The point `t` of the way from point `i` to the next. */
	private put(
		points: Float32Array,
		alphas: Float32Array,
		i: number,
		t: number,
		length: number,
		shown: number
	): void {
		const at = this.count++;
		for (let k = 0; k < 3; k++) {
			const from = points[i * 3 + k];
			this.points[at * 3 + k] = from + (points[i * 3 + 3 + k] - from) * t;
		}
		this.alphas[at] = (alphas[i] + (alphas[i + 1] - alphas[i]) * t) * shown;
		this.lengths[at] = length;
	}

	private copy(from: number, shown: number): void {
		const at = this.count++;
		this.points.copyWithin(at * 3, from * 3, from * 3 + 3);
		this.alphas[at] = this.alphas[from] * shown;
		this.lengths[at] = this.lengths[from];
	}
}

/** One side of the view, positive inside it: ahead of the camera, then within
 *  reach of each edge of the screen. */
function edge(
	plane: number,
	at: number[],
	focal: number,
	halfW: number,
	halfH: number,
	near: number
): number {
	if (plane === 0) return at[2] - near;
	if (plane === 1) return halfW * at[2] - focal * at[0];
	if (plane === 2) return halfW * at[2] + focal * at[0];
	if (plane === 3) return halfH * at[2] - focal * at[1];
	return halfH * at[2] + focal * at[1];
}
