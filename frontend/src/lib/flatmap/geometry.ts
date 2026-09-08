/**
 * Turning places into something drawable. Everything a host or a component
 * draws on the flat map — a track, a chart box, a circle round a landing site,
 * the graticule — arrives here as longitude and latitude and leaves as an SVG
 * path in screen pixels.
 *
 * Two things make that more than a loop of `project`. A straight line between
 * two places is a curve on almost every projection, so segments are split into
 * small steps before projecting; and a line can leave the map, either over the
 * seam of a world map or behind the limb of a globe, so the path breaks into
 * pieces rather than striking across the frame.
 */

import { wrapLon } from './projection';
import type { Viewport } from './view';

/** A place. Longitude east-positive, latitude north-positive, both degrees. */
export interface LonLat {
	lon: number;
	lat: number;
}

/** How the space between two given points is filled in. */
export type Interpolation =
	/** Even in longitude and latitude — what a chart box or a graticule wants,
	 *  since its edges follow the parallels and meridians. */
	| 'linear'
	/** The short way over the sphere, which is what a flight path or a ground
	 *  track means by a straight line. */
	| 'geodesic';

export interface PathOptions {
	interpolate?: Interpolation;
	/** Degrees of arc per step. Smaller is smoother and slower; the default
	 *  keeps a full-frame curve visually smooth without flooding the path. */
	stepDeg?: number;
	/** Join the last point back to the first. */
	closed?: boolean;
}

const DEG = Math.PI / 180;
const RAD = 180 / Math.PI;

/** Beyond this many steps a single segment is not getting any smoother, only
 *  slower — a half-circumference at the default step is already 90. */
const MAX_STEPS = 512;

const DEFAULT_STEP_DEG = 2;

/** Angle between two places, in degrees — how long a segment really is, which
 *  is what decides how finely it needs splitting. */
export function angularDistance(a: LonLat, b: LonLat): number {
	const φ1 = a.lat * DEG;
	const φ2 = b.lat * DEG;
	const dφ = φ2 - φ1;
	const dλ = wrapLon(b.lon - a.lon) * DEG;
	const h = Math.sin(dφ / 2) ** 2 + Math.cos(φ1) * Math.cos(φ2) * Math.sin(dλ / 2) ** 2;
	return 2 * Math.asin(Math.min(1, Math.sqrt(h))) * RAD;
}

/** A place a fraction of the way along the short great-circle arc. */
function slerp(a: LonLat, b: LonLat, t: number): LonLat {
	const d = angularDistance(a, b) * DEG;
	if (d < 1e-12) return a;
	const sinD = Math.sin(d);
	const ka = Math.sin((1 - t) * d) / sinD;
	const kb = Math.sin(t * d) / sinD;
	const φ1 = a.lat * DEG;
	const λ1 = a.lon * DEG;
	const φ2 = b.lat * DEG;
	// The second point is taken the short way round, so a segment over the seam
	// interpolates across it instead of back round the world.
	const λ2 = (a.lon + wrapLon(b.lon - a.lon)) * DEG;
	const x = ka * Math.cos(φ1) * Math.cos(λ1) + kb * Math.cos(φ2) * Math.cos(λ2);
	const y = ka * Math.cos(φ1) * Math.sin(λ1) + kb * Math.cos(φ2) * Math.sin(λ2);
	const z = ka * Math.sin(φ1) + kb * Math.sin(φ2);
	return { lon: Math.atan2(y, x) * RAD, lat: Math.atan2(z, Math.hypot(x, y)) * RAD };
}

/** A place a fraction of the way along, moving evenly in both coordinates. */
function lerp(a: LonLat, b: LonLat, t: number): LonLat {
	return {
		lon: a.lon + wrapLon(b.lon - a.lon) * t,
		lat: a.lat + (b.lat - a.lat) * t
	};
}

/**
 * The given places with enough added between them that the line reads as a
 * curve rather than a chord. Points are not deduplicated: a caller that wants
 * to know which of its own points is which should project them itself.
 */
export function densify(points: readonly LonLat[], options: PathOptions = {}): LonLat[] {
	const interpolate = options.interpolate ?? 'linear';
	const stepDeg = options.stepDeg ?? DEFAULT_STEP_DEG;
	const between = interpolate === 'geodesic' ? slerp : lerp;
	const ring = options.closed && points.length > 2 ? [...points, points[0]] : points;
	if (ring.length < 2) return [...ring];

	const out: LonLat[] = [ring[0]];
	for (let i = 1; i < ring.length; i++) {
		const a = ring[i - 1];
		const b = ring[i];
		const steps = Math.min(MAX_STEPS, Math.max(1, Math.ceil(angularDistance(a, b) / stepDeg)));
		for (let s = 1; s <= steps; s++) out.push(s === steps ? b : between(a, b, s / steps));
	}
	return out;
}

/**
 * Screen points for a run of places, broken wherever the line leaves the map.
 * A break is either a point the projection refuses — the far side of a globe —
 * or a jump wide enough to only be the seam of a world map wrapping round.
 */
export function projectSegments(
	points: readonly LonLat[],
	viewport: Viewport
): [number, number][][] {
	// More than half the world in one step is the seam, not a real move: no
	// densified step is ever that long.
	const seam = viewport.projection.cyclic ? viewport.worldWidthPx / 2 : Infinity;
	const segments: [number, number][][] = [];
	let run: [number, number][] = [];
	let previous: [number, number] | null = null;
	for (const point of points) {
		const screen = viewport.project(point.lon, point.lat);
		if (!screen) {
			if (run.length > 1) segments.push(run);
			run = [];
			previous = null;
			continue;
		}
		if (previous && Math.abs(screen[0] - previous[0]) > seam) {
			if (run.length > 1) segments.push(run);
			run = [];
		}
		run.push(screen);
		previous = screen;
	}
	if (run.length > 1) segments.push(run);
	return segments;
}

function formatSegment(segment: [number, number][], close: boolean): string {
	let d = `M${segment[0][0].toFixed(2)} ${segment[0][1].toFixed(2)}`;
	for (let i = 1; i < segment.length; i++) {
		d += `L${segment[i][0].toFixed(2)} ${segment[i][1].toFixed(2)}`;
	}
	return close ? `${d}Z` : d;
}

/** A hair inside the seam. Exactly ±180 folds to one side of it, so a cut made
 *  there would put both halves of a shape against the same edge of the map. */
const SEAM_INSET = 1e-6;
const SEAM_EDGE = 180 - SEAM_INSET;

/**
 * A closed ring cut where it runs past the seam, into pieces that each stay on
 * one side of it.
 *
 * A shape reaching over the antimeridian has no single outline on a flat map.
 * Drawn whole it jumps back across the width of the world; broken after
 * projection it loses the sides it was cut on and cannot be filled. Cutting it
 * in longitude instead finishes each piece along the seam, which is where the
 * map ends anyway. A ring that covers every longitude — a polar cap — comes
 * back as the two halves it has to be.
 *
 * Longitude is accumulated rather than folded as the ring is walked, so a ring
 * that goes right round the world keeps climbing instead of appearing to turn
 * back on itself.
 */
export function splitRing(ring: readonly LonLat[], centerLon: number): LonLat[][] {
	const inset = (lon: number) =>
		lon > SEAM_EDGE ? SEAM_EDGE : lon < -SEAM_EDGE ? -SEAM_EDGE : lon;
	const n = ring.length;
	if (n < 3) return [ring as LonLat[]];
	const pieces: LonLat[][] = [];
	let piece: LonLat[] = [];
	let lon = wrapLon(ring[0].lon - centerLon);
	piece.push({ lon: inset(lon), lat: ring[0].lat });
	for (let i = 0; i < n; i++) {
		const from = ring[i];
		const to = ring[(i + 1) % n];
		const step = wrapLon(to.lon - from.lon);
		const next = lon + step;
		const side = next > 180 ? 1 : next < -180 ? -1 : 0;
		if (side !== 0) {
			const at = from.lat + (to.lat - from.lat) * ((side * 180 - lon) / step);
			piece.push({ lon: side * SEAM_EDGE, lat: at });
			pieces.push(piece);
			piece = [{ lon: -side * SEAM_EDGE, lat: at }];
			lon = next - side * 360;
		} else {
			lon = next;
		}
		if (i < n - 1) piece.push({ lon: inset(lon), lat: to.lat });
	}
	if (pieces.length === 0) return [ring as LonLat[]];
	// The piece left over runs into the one the walk started with: they are the
	// two ends of a ring that was cut somewhere in the middle.
	pieces[0] = piece.concat(pieces[0]);
	return pieces.map((part) => part.map((at) => ({ lon: at.lon + centerLon, lat: at.lat })));
}

/**
 * An SVG path for a run of places. Empty when none of it is on the map, so a
 * caller can render the result straight into `d` either way.
 *
 * A closed shape is cut at the seam first, so each piece of it is a shape in
 * its own right and can be filled. What the limb of a globe cuts is left open
 * instead: there the shape really does carry on out of sight, and joining the
 * loose ends would draw an edge it does not have.
 */
export function pathFor(
	points: readonly LonLat[],
	viewport: Viewport,
	options: PathOptions = {}
): string {
	if (points.length < 2) return '';
	const rings = options.closed
		? splitRing(points, viewport.projection.centerLon)
		: [points as readonly LonLat[]];
	return rings
		.map((ring) => {
			const segments = projectSegments(densify(ring, options), viewport);
			if (segments.length === 0) return '';
			const whole = segments.length === 1;
			return segments.map((s) => formatSegment(s, Boolean(options.closed) && whole)).join('');
		})
		.join('');
}

/**
 * The edge of the world as a path: the antimeridian walked pole to pole on one
 * side and back down the other.
 *
 * A rectangular projection hands back its border, but a pointed one hands back
 * the curve it actually fills, which is the difference between framing
 * Mollweide or sinusoidal honestly and boxing them in.
 */
export function worldOutline(viewport: Viewport, stepDeg = 2): string {
	const { projection } = viewport;
	// A hair inside the seam: exactly ±180 folds to one side of it, which would
	// trace the western edge twice and leave the eastern one undrawn.
	const edge = 180 - 1e-6;
	const points: [number, number][] = [];
	const side = (lon: number, from: number, to: number) => {
		const step = from < to ? stepDeg : -stepDeg;
		for (let lat = from; step > 0 ? lat <= to : lat >= to; lat += step) {
			const plane = projection.forward(lon, lat);
			if (plane) points.push(viewport.toScreen(plane[0], plane[1]));
		}
	};
	side(projection.centerLon - edge, -90, 90);
	side(projection.centerLon + edge, 90, -90);
	return points.length > 2 ? formatSegment(points, true) : '';
}

/** The four sides of a longitude and latitude box, in order. The corners alone
 *  would be enough on an equirectangular map and wrong on every other one, so
 *  the edges are walked and left for {@link pathFor} to fill in. */
export function boxRing(latMin: number, latMax: number, lonMin: number, lonSpan: number): LonLat[] {
	const lonMax = lonMin + lonSpan;
	// A band covering every longitude has no east or west side to draw; its two
	// parallels are the whole shape, so the ring is walked as one loop round.
	const ring: LonLat[] = [];
	const edge = (lat: number, from: number, to: number) => {
		const steps = Math.max(1, Math.ceil(Math.abs(to - from) / 5));
		for (let i = 0; i <= steps; i++) ring.push({ lon: from + ((to - from) * i) / steps, lat });
	};
	edge(latMin, lonMin, lonMax);
	edge(latMax, lonMax, lonMin);
	return ring;
}

/**
 * A ring of places all the same angular distance from a centre — the flat
 * map's circle, which is a circle on the globe and rarely one on the plane.
 *
 * Swept as a rotation in three dimensions rather than by the spherical
 * bearing formula, which divides by the cosine of the centre's latitude and so
 * collapses a cap drawn round a pole onto a single meridian.
 */
export function smallCircle(center: LonLat, radiusDeg: number, steps = 128): LonLat[] {
	const φ0 = center.lat * DEG;
	const λ0 = center.lon * DEG;
	const c: [number, number, number] = [
		Math.cos(φ0) * Math.cos(λ0),
		Math.cos(φ0) * Math.sin(λ0),
		Math.sin(φ0)
	];
	// Two directions across the ring, at right angles to the centre and to each
	// other. Straight up is parallel to the centre at a pole, so the ring is
	// hung off a fixed axis there; which longitude it then starts at is
	// arbitrary, and it still sweeps all of them.
	let e: [number, number, number] = [-c[1], c[0], 0];
	const len = Math.hypot(e[0], e[1]);
	e = len < 1e-9 ? [1, 0, 0] : [e[0] / len, e[1] / len, 0];
	const n: [number, number, number] = [
		c[1] * e[2] - c[2] * e[1],
		c[2] * e[0] - c[0] * e[2],
		c[0] * e[1] - c[1] * e[0]
	];

	const r = radiusDeg * DEG;
	const sinR = Math.sin(r);
	const cosR = Math.cos(r);
	const ring: LonLat[] = [];
	for (let i = 0; i < steps; i++) {
		const θ = (2 * Math.PI * i) / steps;
		const a = Math.sin(θ) * sinR;
		const b = Math.cos(θ) * sinR;
		const x = c[0] * cosR + e[0] * a + n[0] * b;
		const y = c[1] * cosR + e[1] * a + n[1] * b;
		const z = c[2] * cosR + e[2] * a + n[2] * b;
		ring.push({
			lon: wrapLon(Math.atan2(y, x) * RAD),
			lat: Math.atan2(z, Math.hypot(x, y)) * RAD
		});
	}
	return ring;
}

/** How many points a parallel is walked with. Steps have to stay well under
 *  half the world: a segment exactly that long is ambiguous — both ways round
 *  are the same distance — and would be filled in going whichever way the
 *  longitude fold happens to pick. */
const PARALLEL_STEPS = 24;

/** Meridians and parallels every `stepDeg`, each as its own run of places.
 *  Meridians are drawn pole to pole and parallels right round, so the grid
 *  bends with whatever projection draws it. */
export function graticule(stepDeg = 30): LonLat[][] {
	const lines: LonLat[][] = [];
	for (let lon = -180; lon < 180; lon += stepDeg) {
		lines.push([
			{ lon, lat: -90 },
			{ lon, lat: 90 }
		]);
	}
	// Stopping a hair short of the seam keeps a parallel one run of places
	// rather than a loop closing back across the map.
	const edge = 180 - 1e-6;
	for (let lat = -90 + stepDeg; lat < 90; lat += stepDeg) {
		const parallel: LonLat[] = [];
		for (let i = 0; i <= PARALLEL_STEPS; i++) {
			parallel.push({ lon: -edge + (2 * edge * i) / PARALLEL_STEPS, lat });
		}
		lines.push(parallel);
	}
	return lines;
}
