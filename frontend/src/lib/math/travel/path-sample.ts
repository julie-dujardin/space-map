/**
 * Reading a drawn path at a moment in time.
 *
 * Kept apart from `path.ts`, which builds them: the renderer holds the overlay
 * from the first frame and needs this, while the builder pulls in Lambert, the
 * porkchop and the vehicle catalogue. Everything here works off the sampled arcs
 * alone, so the only import is the vector helpers.
 */

import type { TrajectoryPath } from './path';
import { add, scale, sub, type Vec3 } from './vec3';

/**
 * The half-open range of `path.arcs[index]` that is the crossing proper.
 *
 * An end with a passage down to its orbit hands the last of its arc over: past
 * `trimTo` the conic runs on to the body's *centre*, which is not where the
 * craft goes and is only there because a two-body solve has to end somewhere.
 * Anything reading the arc — drawing along it, or measuring off it — wants this
 * window rather than the whole of it, or it ends up asking what the trip is like
 * at nought kilometres from the Sun.
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
 * Where the craft is, and what that is measured from.
 *
 * The frame is carried rather than assumed because the trip does not have one
 * frame: a planet-frame end is drawn about its own body, so a point on it means
 * nothing until it is put back against that body. Everywhere else this is the
 * path's own centre.
 */
export interface CraftAt {
	/** Position, km, measured from `centerId`. */
	r: Vec3;
	centerId: string;
}

/**
 * Where the craft is at `jd`.
 *
 * Null before it leaves and after it arrives — there is no craft in flight then,
 * and pinning the marker to an end would claim otherwise.
 *
 * Follows what is *drawn*, which is not the arcs alone: an end with a passage
 * takes the last stretch of its crossing over, and past the handover the arc's
 * own samples run on to the body's centre — a place the craft never goes. Read
 * off those, the marker leaves the line it is supposed to be riding and closes
 * on the planet in a straight line while the drawn trip curves away from it.
 *
 * Interpolated between samples by their own dates rather than by counting them:
 * only a coasting arc is sampled evenly in time (see {@link PathArc.jds}).
 */
export function craftPositionAt(path: TrajectoryPath, jd: number): CraftAt | null {
	const first = path.arcs[0];
	const last = path.arcs[path.arcs.length - 1];
	if (!first || !last) return null;

	const passage = (at: 'departure' | 'arrival') => {
		const end = path.endOrbits.find((orbit) => orbit.at === at);
		return end && end.approach.length > 1 ? end : null;
	};
	const departure = passage('departure');
	const arrival = passage('arrival');

	// The ground dates are the trip's real span: liftoff comes hours before the
	// priced departure and touchdown hours after the priced arrival, and the
	// craft is in flight for the climb and the descent too.
	const begin = Math.min(first.startJd, departure?.surfaceJd ?? Infinity);
	const over = Math.max(last.endJd, arrival?.surfaceJd ?? -Infinity);
	if (jd < begin || jd > over) return null;

	// The escape, before the crossing it hands over to.
	if (departure && jd <= departure.jds[departure.jds.length - 1]) {
		return {
			r: between(departure.approach, departure.jds, jd),
			centerId: departure.anchorId
		};
	}
	// The capture, after it. Its periapsis lands hours before the priced arrival —
	// the insertion burn is made there, so the last minutes of the trip are spent
	// in the orbit rather than still falling towards it, and the marker holds.
	// A landing keeps going: its line runs on to the ground, and the marker rides
	// it to touchdown.
	if (arrival && jd >= arrival.jds[0]) {
		return {
			r: between(arrival.approach, arrival.jds, Math.min(jd, arrival.surfaceJd ?? arrival.periJd)),
			centerId: arrival.anchorId
		};
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
