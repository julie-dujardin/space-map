/**
 * Reads a drawn path at a moment in time. Split from `path.ts` (which builds
 * paths) because the renderer needs this from the first frame, before the
 * builder's Lambert/porkchop/vehicle-catalogue imports are needed.
 */

import type { EndOrbitPath, TrajectoryPath } from './path';
import { add, scale, sub, type Vec3 } from './vec3';

/**
 * The half-open range of `path.arcs[index]` that is the crossing proper. Past
 * `trimTo` the conic runs on to the body's centre — an artifact of the
 * two-body solve, not somewhere the craft goes — so anything drawing or
 * measuring the arc wants this window, not the whole of it.
 */
export function crossingWindow(path: TrajectoryPath, index: number): { from: number; to: number } {
	const count = path.arcs[index].points.length;
	const at = (end: 'departure' | 'arrival') => path.endOrbits.find((orbit) => orbit.at === end);
	return {
		from: index === 0 ? (at('departure')?.trimFrom ?? 0) : 0,
		to: index === path.arcs.length - 1 ? (at('arrival')?.trimTo ?? count) : count
	};
}

/**
 * Where the craft is, and what that is measured from — carried rather than
 * assumed because a planet-frame end is drawn about its own body, not the
 * path's centre.
 */
export interface CraftAt {
	/** Position, km, measured from `centerId`. */
	r: Vec3;
	centerId: string;
}

/**
 * Where the craft is at `jd`, or null before departure / after arrival.
 * Follows what is drawn, not the raw arcs: a passage end's approach segment
 * overrides its arc's tail past the handover, since those samples run on to
 * the body's centre — the marker would otherwise cut a straight line to the
 * planet instead of riding the curve. Interpolated by sample date, not index,
 * since only a coasting arc is sampled evenly in time ({@link PathArc.jds}).
 */
export function craftPositionAt(path: TrajectoryPath, jd: number): CraftAt | null {
	const first = path.arcs[0];
	const last = path.arcs[path.arcs.length - 1];
	if (!first || !last) return null;

	const endAt = (at: 'departure' | 'arrival') =>
		path.endOrbits.find((orbit) => orbit.at === at) ?? null;
	const departure = endAt('departure');
	const arrival = endAt('arrival');
	// The stretch of line an end draws between its orbit and the arc. A trip that
	// stays at one body crosses no sphere of influence and lands on nothing, so
	// its ends are rings alone and the arc hands straight over to them.
	const lineOf = (end: EndOrbitPath | null) => (end && end.approach.length > 1 ? end : null);
	const departureLine = lineOf(departure);
	const arrivalLine = lineOf(arrival);
	/** The end's orbit as a dated revolution, where the drawing has one. */
	const ringOf = (end: typeof departure) =>
		end && end.pointJds && end.points.length > 1 && end.pointJds.length === end.points.length
			? { points: end.points, jds: end.pointJds }
			: null;
	const startRing = ringOf(departure);
	const finalRing = arrival?.surfaceJd === undefined ? ringOf(arrival) : null;

	// Ground dates are the real span: liftoff/touchdown are hours before/after
	// the priced departure/arrival, and the craft is in flight for both. An
	// arrival's line can outlast the crossing too — the descent's hours, or an
	// aerobraking campaign's months.
	const leaves = Math.min(first.startJd, departure?.surfaceJd ?? Infinity);
	const settles = Math.max(
		last.endJd,
		arrival?.surfaceJd ?? arrivalLine?.jds[arrivalLine.jds.length - 1] ?? -Infinity
	);
	// The dated end orbits stretch that by a revolution each way: the craft is in
	// the starting orbit before it leaves and in the final one after it settles.
	// Measured off the trip rather than off the rings' own clocks, which start at
	// their periapses — a plane turn's coast, or a crossing priced to the body's
	// centre, can put the craft most of a revolution from either.
	const begin = startRing ? leaves - period(startRing) : leaves;
	const over = finalRing ? settles + period(finalRing) : settles;
	if (jd < begin || jd > over) return null;

	// Still going round the starting orbit, before the trip leaves it — at the
	// line's first date where there is one, and at the arc's own otherwise.
	if (departure && startRing && jd < (departureLine?.jds[0] ?? first.startJd)) {
		return { r: onRing(startRing, jd), centerId: departure.anchorId };
	}
	// The escape, before the crossing it hands over to.
	if (departureLine && jd <= departureLine.jds[departureLine.jds.length - 1]) {
		return {
			r: between(departureLine.approach, departureLine.jds, jd),
			centerId: departureLine.anchorId
		};
	}
	// The capture, after it. Periapsis lands before the priced arrival (the
	// insertion burn happens there), and a landing's line runs on to the ground.
	if (arrival && jd >= (arrivalLine?.jds[0] ?? last.endJd)) {
		// The line's own last date, not `periJd`: an aero arrival keeps flying
		// past periapsis, out to its trim burn or through its campaign.
		const until = arrival.surfaceJd ?? arrivalLine?.jds[arrivalLine.jds.length - 1] ?? last.endJd;
		// Past the line, the craft is in the orbit the trip ends in, at whatever
		// phase of it the date falls on. An end with no line is in it from the
		// moment the arc reaches it, there being nothing in between.
		if (finalRing && (!arrivalLine || jd > until)) {
			return { r: onRing(finalRing, jd), centerId: arrival.anchorId };
		}
		if (arrivalLine) {
			return {
				r: between(arrivalLine.approach, arrivalLine.jds, Math.min(jd, until)),
				centerId: arrival.anchorId
			};
		}
	}

	// Between two arcs — at a swing-by, say — the later one owns the instant.
	const index = path.arcs.findIndex((a) => jd >= a.startJd && jd <= a.endJd);
	const at = index >= 0 ? index : path.arcs.length - 1;
	const arc = path.arcs[at];
	const { points, jds } = arc;
	if (points.length === 0) return null;
	if (points.length === 1 || jds.length !== points.length) {
		return { r: points[0], centerId: path.centerId };
	}
	const { from, to } = crossingWindow(path, at);
	return { r: between(points, jds, jd, from, to), centerId: path.centerId };
}

/** A dated revolution: `points` with the date each is passed. */
interface Ring {
	points: readonly Vec3[];
	jds: readonly number[];
}

/** How long one revolution of `ring` takes, days. */
function period(ring: Ring): number {
	return ring.jds[ring.jds.length - 1] - ring.jds[0];
}

/**
 * Where the craft is on `ring` at `jd`, wrapped by whole revolutions.
 *
 * The ring is one revolution of an orbit the craft keeps flying, and its clock
 * starts at its own periapsis — which is not when the craft joins it. An aero
 * arrival joins half a revolution early, and a plane turn's coast can hand over
 * most of a revolution late; either way the date wanted is a phase of the
 * orbit, not a moment inside one arbitrary revolution of it.
 */
function onRing(ring: Ring, jd: number): Vec3 {
	const revolution = period(ring);
	const from = ring.jds[0];
	const at = revolution > 0 ? from + ((((jd - from) % revolution) + revolution) % revolution) : jd;
	return between(ring.points, ring.jds, at);
}

/** The point at `jd` along a dated run of samples, clamped to its ends. */
function between(
	points: readonly Vec3[],
	jds: readonly number[],
	jd: number,
	from = 0,
	to = points.length
): Vec3 {
	// A window trimmed down to a single sample is that sample; there is nothing to
	// interpolate along and the next index is outside it.
	if (to - from < 2) return points[from];
	let i = from + 1;
	while (i < to - 1 && jds[i] < jd) i++;
	const span = jds[i] - jds[i - 1];
	const t = span > 0 ? Math.min(1, Math.max(0, (jd - jds[i - 1]) / span)) : 0;
	return add(points[i - 1], scale(sub(points[i], points[i - 1]), t));
}
