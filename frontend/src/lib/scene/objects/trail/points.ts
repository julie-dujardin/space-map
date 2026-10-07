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

/**
 * Fill `fullArr` with the full-orbit fade and `trailArr` with the partial
 * fade (~1/3 of the orbit from the body); non-trail bodies copy the full ramp.
 *
 * `isOpenCurve` sets only the full ramp's floor: open curves (SGP4 window,
 * chebyshev buffer) fade to 0 since the oldest sample is the tail tip; closed
 * curves (Kepler ellipse) fade to a non-zero floor so the loop seam doesn't pop.
 */
export function writeTrailAlphas(
	fullArr: Float32Array,
	trailArr: Float32Array,
	isOpenCurve: boolean,
	useTrail: boolean
): void {
	const fullMax = 0.55;
	const fullMin = isOpenCurve ? 0 : fullMax / 3;
	const last = fullArr.length - 1;
	for (let k = 0; k < fullArr.length; k++) {
		fullArr[k] = fullMax - (last > 0 ? k / last : 0) * (fullMax - fullMin);
	}
	if (useTrail) {
		const trailLen = Math.round(NUM_TRAIL_POINTS / 3);
		const trailMax = 0.35;
		trailArr.fill(0);
		for (let k = 0; k < Math.min(trailLen, trailArr.length); k++) {
			trailArr[k] = trailMax - (k / (trailLen - 1)) * trailMax;
		}
	} else {
		trailArr.set(fullArr);
	}
}
