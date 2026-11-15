/**
 * The frame of a star chart: a camera at the Sun, aimed at a figure, with north
 * up and east to the left. Directions are unit vectors in ICRS axes.
 *
 * The projection is stereographic. It keeps shapes at every field of view, and
 * it holds a figure that spans more than half of the sky. A plane unit is one
 * radian at the centre of the frame.
 */

import { cross, dot, normalize, type Vec3 } from '$lib/math/travel/vec3';

export interface ChartFrame {
	/** To the west, which is the right of the picture. */
	right: Vec3;
	up: Vec3;
	/** The centre of the picture. */
	forward: Vec3;
	/** Plane units from the centre to the top edge. */
	halfHeight: number;
	/** CSS pixels. */
	width: number;
	height: number;
}

export interface FrameOptions {
	/** CSS pixels. Their ratio is the aspect of the frame. */
	width: number;
	height: number;
	/** Sky around the figure, as a share of its half size. */
	margin?: number;
	/** The smallest field of view on the short side, degrees. */
	minFieldDeg?: number;
}

/** Room for the names of the stars at the edge of a figure. */
export const DEFAULT_MARGIN = 0.3;
/** A cube face of 4,096 px holds 46 px per degree. */
export const DEFAULT_MIN_FIELD_DEG = 8;

const NORTH: Vec3 = [0, 0, 1];
const RA_ZERO: Vec3 = [1, 0, 0];

/** The axes of a camera aimed at `forward`. At a pole, RA 0h is up. */
function axes(forward: Vec3): Pick<ChartFrame, 'right' | 'up' | 'forward'> {
	const towards = Math.abs(dot(forward, NORTH)) > 1 - 1e-9 ? RA_ZERO : NORTH;
	const lean = dot(towards, forward);
	const up = normalize([
		towards[0] - lean * forward[0],
		towards[1] - lean * forward[1],
		towards[2] - lean * forward[2]
	]);
	return { right: cross(forward, up), up, forward };
}

type Axes = ReturnType<typeof axes>;

/** A direction on the plane. The point opposite the centre has no place. */
function toPlane({ right, up, forward }: Axes, direction: Vec3): [number, number] {
	const scale = 2 / Math.max(1 + dot(direction, forward), 1e-9);
	return [dot(direction, right) * scale, dot(direction, up) * scale];
}

function fromPlane({ right, up, forward }: Axes, x: number, y: number): Vec3 {
	const r2 = x * x + y * y;
	const a = (4 * x) / (4 + r2);
	const b = (4 * y) / (4 + r2);
	const c = (4 - r2) / (4 + r2);
	return [
		a * right[0] + b * up[0] + c * forward[0],
		a * right[1] + b * up[1] + c * forward[1],
		a * right[2] + b * up[2] + c * forward[2]
	];
}

/** The centre of the smallest cap that holds the directions, to a fraction of
 *  a degree. A mean leans to the crowded end of a long figure. */
function capCentre(directions: readonly Vec3[]): Vec3 {
	let centre = directions[0];
	for (let step = 1; step <= 200; step++) {
		let far = directions[0];
		for (const direction of directions) {
			if (dot(direction, centre) < dot(far, centre)) far = direction;
		}
		centre = normalize([
			centre[0] + (far[0] - centre[0]) / (step + 1),
			centre[1] + (far[1] - centre[1]) / (step + 1),
			centre[2] + (far[2] - centre[2]) / (step + 1)
		]);
	}
	return centre;
}

interface Box {
	axes: Axes;
	halfWidth: number;
	halfHeight: number;
}

/** The camera that puts the box of the directions at the centre of its plane. */
function centredBox(directions: readonly Vec3[]): Box {
	let aimed = axes(capCentre(directions));
	let halfWidth = 0;
	let halfHeight = 0;
	// The box moves as the camera turns to its centre, so the aim is repeated.
	for (let pass = 0; pass < 4; pass++) {
		let minX = Infinity;
		let maxX = -Infinity;
		let minY = Infinity;
		let maxY = -Infinity;
		for (const direction of directions) {
			const [x, y] = toPlane(aimed, direction);
			minX = Math.min(minX, x);
			maxX = Math.max(maxX, x);
			minY = Math.min(minY, y);
			maxY = Math.max(maxY, y);
		}
		halfWidth = (maxX - minX) / 2;
		halfHeight = (maxY - minY) / 2;
		aimed = axes(normalize(fromPlane(aimed, (minX + maxX) / 2, (minY + maxY) / 2)));
	}
	return { axes: aimed, halfWidth, halfHeight };
}

function minHalf(minFieldDeg: number): number {
	return 2 * Math.tan((minFieldDeg * Math.PI) / 720);
}

/**
 * The frame that holds every direction with a margin. A frame wider or taller
 * than the figure shows more sky: the figure keeps its shape.
 */
export function fitFrame(directions: readonly Vec3[], options: FrameOptions): ChartFrame {
	const { width, height, margin = DEFAULT_MARGIN, minFieldDeg = DEFAULT_MIN_FIELD_DEG } = options;
	const box = centredBox(directions);
	const aspect = width / height;
	const grown = Math.max(box.halfHeight, box.halfWidth / aspect) * (1 + margin);
	const least = minHalf(minFieldDeg) / Math.min(aspect, 1);
	return { ...box.axes, halfHeight: Math.max(grown, least), width, height };
}

/** Sky around the figure in a frame that fills an area, as a share of its
 *  half size. The figure takes five eighths of the area at most. */
export const FILL_MARGIN = 0.6;
/** CSS pixels per degree at most in such a frame. The finest sky tiles hold
 *  182 px per degree, and a chart paints two pixels per CSS pixel. */
export const FILL_MAX_SCALE = 100;

export interface FillOptions {
	/** CSS pixels of the area. */
	width: number;
	height: number;
	/** CSS pixels at the left and right edges, and at the top and bottom
	 *  edges, that the figure stays out of. Sky still fills them. */
	clear?: readonly [number, number];
	margin?: number;
	minFieldDeg?: number;
}

/**
 * The frame that fills an area of any shape. The figure is at the centre at
 * one scale in both axes; the rest of the area is the sky around it.
 */
export function fillFrame(directions: readonly Vec3[], options: FillOptions): ChartFrame {
	const {
		width,
		height,
		clear = [0, 0],
		margin = FILL_MARGIN,
		minFieldDeg = DEFAULT_MIN_FIELD_DEG
	} = options;
	const box = centredBox(directions);
	// A small area keeps half of each side for the figure.
	const free = [
		Math.max(width - 2 * clear[0], width / 2),
		Math.max(height - 2 * clear[1], height / 2)
	];
	// Plane units per CSS pixel.
	const step = Math.max(
		(2 * box.halfWidth * (1 + margin)) / free[0],
		(2 * box.halfHeight * (1 + margin)) / free[1],
		(2 * minHalf(minFieldDeg)) / Math.min(width, height),
		Math.PI / 180 / FILL_MAX_SCALE
	);
	return { ...box.axes, halfHeight: (step * height) / 2, width, height };
}

/** Width over height of the figure with its margin, held between two limits so
 *  that a line of stars does not give a sliver. */
export function figureAspect(
	directions: readonly Vec3[],
	min: number,
	max: number,
	minFieldDeg = DEFAULT_MIN_FIELD_DEG
): number {
	const box = centredBox(directions);
	const least = minHalf(minFieldDeg);
	const aspect = Math.max(box.halfWidth, least) / Math.max(box.halfHeight, least);
	return Math.min(Math.max(aspect, min), max);
}

/** A direction in CSS pixels from the top left of the frame. */
export function project(frame: ChartFrame, direction: Vec3): [number, number] {
	const [x, y] = toPlane(frame, direction);
	const scale = frame.height / (2 * frame.halfHeight);
	return [frame.width / 2 + x * scale, frame.height / 2 - y * scale];
}

/** Plane units from the centre to the right edge and to the top edge. A sky
 *  source reads the rays of its pixels from these and the axes. */
export function planeHalf(frame: ChartFrame): [number, number] {
	return [(frame.halfHeight * frame.width) / frame.height, frame.halfHeight];
}

/** The direction at a fraction of the frame from its top-left corner. */
export function directionAt(frame: ChartFrame, fx: number, fy: number): Vec3 {
	const [halfWidth, halfHeight] = planeHalf(frame);
	return fromPlane(frame, (2 * fx - 1) * halfWidth, (1 - 2 * fy) * halfHeight);
}

/** Degrees of sky in one CSS pixel at the centre of the frame. */
export function centreScaleDeg(frame: ChartFrame): number {
	return ((2 * frame.halfHeight) / frame.height) * (180 / Math.PI);
}
