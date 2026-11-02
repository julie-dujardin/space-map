/**
 * Where the camera goes to show a trip whole.
 *
 * The camera orbits the target of the trip, so the target is at the centre of
 * the view. Between two star systems, the vantage puts the origin in the part of
 * the screen that the page leaves open, and sees the line between the two from
 * the side. A trip that stays inside one system is a ball, which the vantage
 * puts in that part of the screen. When the camera already shows the trip, it
 * stays where it is.
 *
 * Positions are in scene units on the scene's axes.
 */

import {
	add,
	cross,
	dot,
	norm,
	normalize,
	scale,
	sub,
	type Vec3 as TravelVec3
} from '$lib/math/travel/vec3';
import type { Vec3 } from '$lib/scene/animation/math';

/** Share of the narrower half field of view at which a new vantage sees the
 *  origin, when the open part of the screen allows it. */
const FILL = 0.7;
/** Nearer to the centre than this share, the line reads as a point. */
const FILL_MIN = 0.25;
/** The camera shows the trip only from at least this share of the trip's
 *  length. Nearer in, the line runs out past the camera. */
const MIN_DISTANCE = 0.5;
/** Angle between the line and a new vantage, seen from the target. The origin
 *  end is then the nearer one. */
const VANTAGE_RAD = (60 * Math.PI) / 180;
/** Vantages tried round the line. The first ones are nearest to the camera. */
const SIDES = 72;
/** Room round the origin for the labels of its end, px. A label runs to the
 *  right of its point in every script, so it needs more room on that side. */
const LABEL_ROOM_PX = 40;
const LABEL_WIDTH_PX = 128;
/** A side direction shorter than this share of its vector is no direction. */
const SIDE_MIN = 1e-3;
/** Height of a vantage on a ball above the plane it looks at. */
const BALL_ELEVATION_RAD = (45 * Math.PI) / 180;
/** The camera still shows a ball from this many times its least distance. */
const BALL_SLACK = 3;
/** The least room a ball takes on each side of the centre, in normalised device
 *  units. A sheet that covers half of a phone leaves none below the centre. */
const BALL_ROOM_MIN = 0.25;
/** A ring of this share of the line, or wider, sets the scale of the view. */
const RING_SHARE = 1 / 4;
/** Scene +Y: ecliptic north. */
const NORTH: TravelVec3 = [0, 1, 0];
const EAST: TravelVec3 = [1, 0, 0];

/** What the page covers of the map, px from each edge. */
export interface ScreenInsets {
	top: number;
	right: number;
	bottom: number;
	left: number;
}

/** How far the origin can be from the centre of the screen toward each edge,
 *  in normalised device units: 1 is the edge. */
export interface OpenArea {
	top: number;
	right: number;
	bottom: number;
	left: number;
}

/** The camera that the vantage is for. */
export interface TripCamera {
	/** Vertical field of view, deg. */
	fovDeg: number;
	/** Width over height. */
	aspect: number;
	/** Screen up, scene axes. */
	up: Vec3;
	open: OpenArea;
}

export interface TripVantage {
	/** Camera position from the target, scene units. */
	offset: Vec3;
	/** True when this is where the camera already is. */
	kept: boolean;
}

/** Half the narrower field of view of a camera, rad. `fovDeg` is vertical. */
export function narrowHalfFov(fovDeg: number, aspect: number): number {
	const half = (fovDeg * Math.PI) / 360;
	return aspect < 1 ? Math.atan(Math.tan(half) * aspect) : half;
}

/** The open part of a screen of `width` × `height` px, less room for the
 *  labels at the origin. Never less than nothing on a side. */
export function openArea(insets: ScreenInsets, width: number, height: number): OpenArea {
	const share = (inset: number, size: number) => Math.max(0, 1 - (2 * inset) / size);
	return {
		top: share(insets.top + LABEL_ROOM_PX, height),
		right: share(insets.right + LABEL_WIDTH_PX, width),
		bottom: share(insets.bottom + LABEL_ROOM_PX, height),
		left: share(insets.left + LABEL_ROOM_PX, width)
	};
}

/**
 * The vantage that shows the trip from `origin` to `target` with the camera at
 * `camera`. Of the vantages that put the origin in the open area as far out
 * as the field allows, it takes the one nearest to the camera, so that the
 * move is short. `ring` is the widest ring at either end. A ring that is wide
 * against the line goes in the view with it. Null when the two ends are in one
 * place.
 */
export function tripVantage(
	target: Vec3,
	origin: Vec3,
	camera: Vec3,
	view: TripCamera,
	ring = 0
): TripVantage | null {
	const line = sub(origin, target);
	const length = norm(line);
	const narrow = narrowHalfFov(view.fovDeg, view.aspect);
	if (!(length > 0) || !(narrow > 0)) return null;
	if (ring >= RING_SHARE * length) {
		return ballVantage(target, target, length + ring, null, camera, view);
	}
	const offset = sub(camera, target);
	if (shows(offset, line, length, view, narrow)) {
		return { offset: [offset[0], offset[1], offset[2]], kept: true };
	}

	const along = scale(line, 1 / length);
	const first = sideOf(offset, along) ?? sideOf(NORTH, along) ?? sideOf(EAST, along);
	if (!first) return null;
	const second = cross(along, first);
	const full = Math.tan(FILL * narrow);
	const fullDistance = distanceAt(length, full);
	let best: { direction: TravelVec3; reach: number } | null = null;
	for (let i = 0; i < SIDES; i++) {
		// 0, -1, +1, -2, +2, …: out from the side the camera is on.
		const step = i % 2 === 0 ? i / 2 : -(i + 1) / 2;
		const turn = (2 * Math.PI * step) / SIDES;
		const side = add(scale(first, Math.cos(turn)), scale(second, Math.sin(turn)));
		const direction = add(scale(along, Math.cos(VANTAGE_RAD)), scale(side, Math.sin(VANTAGE_RAD)));
		const at = project(line, scale(direction, fullDistance), view);
		if (!at) continue;
		const reach = full * fitShare(at, view.open);
		// Only a clear gain moves the camera farther round from where it is.
		if (!best || reach > best.reach * (1 + 1e-9)) best = { direction, reach };
	}
	if (!best) return null;
	// With no room anywhere, the origin goes as near the centre as still reads.
	const reach = Math.max(best.reach, Math.tan(FILL_MIN * narrow));
	const [x, y, z] = scale(best.direction, distanceAt(length, reach));
	return { offset: [x, y, z], kept: false };
}

/**
 * The vantage that shows a ball of `radius` about `center` from `target`, which
 * can be anywhere in it. It looks down on the plane of the unit vector `normal`,
 * north if null, and takes the side of that plane where the ball is largest in the
 * open area. Null when the ball has no size or no side fits it.
 */
export function ballVantage(
	target: Vec3,
	center: Vec3,
	radius: number,
	normal: Vec3 | null,
	camera: Vec3,
	view: TripCamera
): TripVantage | null {
	if (!(radius > 0)) return null;
	const pole = normal ?? NORTH;
	const ball = sub(center, target);
	const offset = sub(camera, target);
	const distance = norm(offset);
	if (distance > 0) {
		const least = ballDistance(ball, radius, scale(offset, 1 / distance), view);
		if (least !== null && distance >= least && distance <= BALL_SLACK * least) {
			return { offset: [offset[0], offset[1], offset[2]], kept: true };
		}
	}

	const first = sideOf(offset, pole) ?? sideOf(EAST, pole) ?? sideOf(NORTH, pole);
	if (!first) return null;
	const second = cross(pole, first);
	let best: { direction: TravelVec3; distance: number } | null = null;
	for (let i = 0; i < SIDES; i++) {
		const turn = (2 * Math.PI * i) / SIDES;
		const side = add(scale(first, Math.cos(turn)), scale(second, Math.sin(turn)));
		const direction = add(
			scale(side, Math.cos(BALL_ELEVATION_RAD)),
			scale(pole, Math.sin(BALL_ELEVATION_RAD))
		);
		const away = ballDistance(ball, radius, direction, view);
		if (away !== null && (!best || away < best.distance)) best = { direction, distance: away };
	}
	if (!best) return null;
	const [x, y, z] = scale(best.direction, best.distance);
	return { offset: [x, y, z], kept: false };
}

/** Least distance from the target along the unit vector `back` at which a ball at
 *  `center` from the target is in the open area. Null when the camera looks along
 *  its up. */
function ballDistance(
	center: TravelVec3,
	radius: number,
	back: TravelVec3,
	view: TripCamera
): number | null {
	const right = cross(view.up, back);
	const width = norm(right);
	if (!(width > SIDE_MIN)) return null;
	const across = scale(right, 1 / width);
	const up = cross(back, across);
	const tanY = Math.tan((view.fovDeg * Math.PI) / 360);
	const tanX = tanY * view.aspect;
	const room = (share: number, tan: number) => Math.max(share, BALL_ROOM_MIN) * tan;
	const x = dot(center, across);
	const y = dot(center, up);
	const depth = Math.max(
		(x + radius) / room(view.open.right, tanX),
		(radius - x) / room(view.open.left, tanX),
		(y + radius) / room(view.open.top, tanY),
		(radius - y) / room(view.open.bottom, tanY)
	);
	// Measured from the near side of the ball, which looks the largest.
	return depth + dot(center, back) + radius;
}

/** Distance from the target at which the origin, `length` off at the vantage
 *  angle, is seen `tanAngle` off the centre. */
function distanceAt(length: number, tanAngle: number): number {
	return length * (Math.cos(VANTAGE_RAD) + Math.sin(VANTAGE_RAD) / tanAngle);
}

/**
 * Where a camera at `offset` from the target, looking at it, sees the point at
 * `point` from the target: normalised device units, and the tangent of its
 * angle off the centre. Null when the point is behind the camera or the
 * camera looks along its up.
 */
function project(
	point: TravelVec3,
	offset: TravelVec3,
	view: TripCamera
): { x: number; y: number; tan: number } | null {
	const back = normalize(offset);
	const right = cross(view.up, back);
	const width = norm(right);
	if (!(width > SIDE_MIN)) return null;
	const across = scale(right, 1 / width);
	const up = cross(back, across);
	const from = sub(point, offset);
	const depth = -dot(from, back);
	if (!(depth > 0)) return null;
	const x = dot(from, across) / depth;
	const y = dot(from, up) / depth;
	const tanY = Math.tan((view.fovDeg * Math.PI) / 360);
	return { x: x / (tanY * view.aspect), y: y / tanY, tan: Math.hypot(x, y) };
}

/** The share of its distance from the centre that a point at `at` can keep
 *  and still be in the open area, at most 1. */
function fitShare(at: { x: number; y: number }, open: OpenArea): number {
	let share = 1;
	if (at.x > 0) share = Math.min(share, open.right / at.x);
	if (at.x < 0) share = Math.min(share, open.left / -at.x);
	if (at.y > 0) share = Math.min(share, open.top / at.y);
	if (at.y < 0) share = Math.min(share, open.bottom / -at.y);
	return share;
}

/** Whether a camera at `offset` from the target shows the line to the origin,
 *  which is at `line` from the target: the origin in the open area and not on
 *  top of the target. */
function shows(
	offset: TravelVec3,
	line: TravelVec3,
	length: number,
	view: TripCamera,
	narrow: number
): boolean {
	if (norm(offset) < MIN_DISTANCE * length) return false;
	const at = project(line, offset, view);
	return at !== null && at.tan >= Math.tan(FILL_MIN * narrow) && fitShare(at, view.open) >= 1;
}

/** The unit part of `v` across `along`; null when `v` runs along it. */
function sideOf(v: TravelVec3, along: TravelVec3): TravelVec3 | null {
	const across = sub(v, scale(along, dot(v, along)));
	const length = norm(across);
	return length > SIDE_MIN * norm(v) ? scale(across, 1 / length) : null;
}
