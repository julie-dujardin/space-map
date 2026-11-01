import type { PositionedBody } from '$lib/types/objects';

export const NUM_TRAIL_POINTS = 512;

/** Sample a trail starts on when only the place of the body is known: the
 *  nearest one, or the one before it when the body is between the two. */
function nearestStart(curve: [number, number, number][], at: [number, number, number]): number {
	let nearest = 0;
	let best = Infinity;
	for (let j = 0; j < curve.length; j++) {
		const d = (curve[j][0] - at[0]) ** 2 + (curve[j][1] - at[1]) ** 2 + (curve[j][2] - at[2]) ** 2;
		if (d < best) {
			best = d;
			nearest = j;
		}
	}

	const prev = Math.max(nearest - 1, 0);
	const next = Math.min(nearest + 1, curve.length - 1);
	const distPrev =
		(curve[prev][0] - at[0]) ** 2 + (curve[prev][1] - at[1]) ** 2 + (curve[prev][2] - at[2]) ** 2;
	const distNext =
		(curve[next][0] - at[0]) ** 2 + (curve[next][1] - at[1]) ** 2 + (curve[next][2] - at[2]) ** 2;
	return distPrev < distNext ? prev : nearest;
}

/**
 * Vertices of a trail, relative to the orbit centre: the body, then the curve
 * samples behind it. `start` is the first of those samples, for a curve whose
 * samples are in date order. Without it the nearest sample decides.
 */
export function buildTrailPoints(
	body: PositionedBody,
	curve: [number, number, number][],
	isOpenCurve: boolean,
	cx: number,
	cy: number,
	cz: number,
	start?: number
): [number, number, number][] {
	// An SGP4 curve is empty when every sample fails, for a decayed satellite.
	if (curve.length === 0) return [];

	// A planet that borrows the elements of its barycentre has `trailAnchor`:
	// the curve passes through the barycentre, not through the planet.
	const anchor = body.trailAnchor ?? body.position;
	if (!anchor) return [];
	const bodyLocal: [number, number, number] = [anchor[0] - cx, anchor[1] - cy, anchor[2] - cz];
	const trailStart = start ?? nearestStart(curve, bodyLocal);

	const points: [number, number, number][] = [bodyLocal];
	if (isOpenCurve) {
		for (let k = 0; k < NUM_TRAIL_POINTS - 1; k++) {
			const idx = Math.max(trailStart - k, 0);
			points.push(curve[idx]);
			if (idx === 0) break;
		}
	} else {
		for (let k = 0; k < NUM_TRAIL_POINTS - 1; k++) {
			points.push(
				curve[(((trailStart - k) % NUM_TRAIL_POINTS) + NUM_TRAIL_POINTS) % NUM_TRAIL_POINTS]
			);
		}
		points.push(bodyLocal); // close the loop
	}
	return points.filter((p) => p.every(Number.isFinite));
}

/** Length of the segment that ends on vertex `k`. */
function segmentLength(posArr: Float32Array, k: number): number {
	const i = k * 3;
	return Math.hypot(
		posArr[i] - posArr[i - 3],
		posArr[i + 1] - posArr[i - 2],
		posArr[i + 2] - posArr[i - 1]
	);
}

/**
 * Fill `fullArr` with the fade of the whole trail and `trailArr` with the fade
 * of its nearest third. A body with no partial trail copies the full ramp.
 *
 * An open curve is measured by length, because its vertices can be few and
 * unevenly spaced, and it fades to 0 at its tip. A closed curve is measured by
 * vertex and fades to a floor, so that the loop seam stays hidden.
 */
export function writeTrailAlphas(
	fullArr: Float32Array,
	trailArr: Float32Array,
	posArr: Float32Array,
	isOpenCurve: boolean,
	useTrail: boolean
): void {
	const fullMax = 0.55;
	const fullMin = isOpenCurve ? 0 : fullMax / 3;
	const trailMax = 0.35;
	const last = fullArr.length - 1;
	// `fullArr` holds the distance from the body until the ramps replace it.
	fullArr[0] = 0;
	for (let k = 1; k <= last; k++) {
		fullArr[k] = fullArr[k - 1] + (isOpenCurve ? segmentLength(posArr, k) : 1);
	}
	const end = fullArr[last];
	for (let k = 0; k <= last; k++) {
		const share = end > 0 ? fullArr[k] / end : 0;
		fullArr[k] = fullMax - share * (fullMax - fullMin);
		trailArr[k] = useTrail ? trailMax * Math.max(0, 1 - 3 * share) : fullArr[k];
	}
}
