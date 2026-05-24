import type { PositionedBody } from '$lib/types/objects';

export const NUM_TRAIL_POINTS = 512;

/** Anchor the static curve at the body's current position so the trail trails *behind* it. */
export function buildTrailPoints(
	body: PositionedBody,
	curve: [number, number, number][],
	isOpenCurve: boolean,
	cx: number,
	cy: number,
	cz: number
): [number, number, number][] {
	// sgp4Curve returns [] when every sample fails (e.g. decayed satellite);
	// callers gate on validPoints.length < 2 and draw nothing in that case.
	if (curve.length === 0) return [];

	// Anchor at `trailAnchor` when set — borrowed-barycenter bodies need the
	// trail's bright end to sit on the barycenter the curve actually traces,
	// not on the body's own offset position (which would kink the line into
	// the curve). Falls back to `body.position` for everyone else.
	const anchor = body.trailAnchor ?? body.position;
	const bodyLocal: [number, number, number] = [anchor[0] - cx, anchor[1] - cy, anchor[2] - cz];

	let nearest = 0;
	let best = Infinity;
	for (let j = 0; j < curve.length; j++) {
		const d =
			(curve[j][0] - bodyLocal[0]) ** 2 +
			(curve[j][1] - bodyLocal[1]) ** 2 +
			(curve[j][2] - bodyLocal[2]) ** 2;
		if (d < best) {
			best = d;
			nearest = j;
		}
	}

	const prev = Math.max(nearest - 1, 0);
	const next = Math.min(nearest + 1, curve.length - 1);
	const distPrev =
		(curve[prev][0] - bodyLocal[0]) ** 2 +
		(curve[prev][1] - bodyLocal[1]) ** 2 +
		(curve[prev][2] - bodyLocal[2]) ** 2;
	const distNext =
		(curve[next][0] - bodyLocal[0]) ** 2 +
		(curve[next][1] - bodyLocal[1]) ** 2 +
		(curve[next][2] - bodyLocal[2]) ** 2;
	const trailStart = distPrev < distNext ? prev : nearest;

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
 * Fill `fullArr` with the full-orbit alpha ramp (fades along the whole curve)
 * and `trailArr` with the partial-trail ramp (fade from the body over ~1/3 of
 * the orbit). For non-trail bodies the trail ramp is a copy of the full ramp.
 *
 * `isOpenCurve` controls only the full-ramp endpoint: open curves (SGP4 sliding
 * window, chebyshev time-ordered buffer) fade to 0 since the oldest sample is
 * the tail tip; closed curves (Kepler ellipse) fade to a non-zero floor so the
 * loop seam doesn't pop. The partial-trail ramp is the same shape regardless.
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
