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
 * Where the craft is at `jd`, in the transfer frame, km.
 *
 * Null before it leaves and after it arrives — there is no craft in flight then,
 * and pinning the marker to an end would claim otherwise.
 *
 * Interpolated between samples by their own dates rather than by counting them:
 * only a coasting arc is sampled evenly in time (see {@link PathArc.jds}).
 */
export function craftPositionAt(path: TrajectoryPath, jd: number): Vec3 | null {
	const first = path.arcs[0];
	const last = path.arcs[path.arcs.length - 1];
	if (!first || !last) return null;
	if (jd < first.startJd || jd > last.endJd) return null;

	// Between two arcs — at a swing-by, say — the later one owns the instant.
	const arc = path.arcs.find((a) => jd >= a.startJd && jd <= a.endJd) ?? last;
	const { points, jds } = arc;
	if (points.length === 0) return null;
	if (points.length === 1 || jds.length !== points.length) return points[0];

	let i = 1;
	while (i < jds.length - 1 && jds[i] < jd) i++;
	const span = jds[i] - jds[i - 1];
	const t = span > 0 ? Math.min(1, Math.max(0, (jd - jds[i - 1]) / span)) : 0;
	return add(points[i - 1], scale(sub(points[i], points[i - 1]), t));
}
