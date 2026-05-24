import type { Line, Mesh, Vector3 } from 'three';
import { orbitalElementsToCurve, sgp4Curve } from '$lib/math/orbit/curves';
import { propagateOrbitAngles } from '$lib/math/orbit/position';
import type { PositionedBody } from '$lib/types/objects';
import type { TrailBuffer } from '$lib/fetch/position/trail-buffer';
import { NUM_TRAIL_POINTS, buildTrailPoints } from './points';
import { commitTrail, getTrailWorkingArrays, writeFatTrailVertices } from './geometry';
import { writeBufferVerticesWithLiveHead } from './builder';

// Re-render the precessing-elements curve when accumulated drift on Ω or ω
// exceeds this many degrees. At 0.01° the chord offset stays sub-body-radius
// even for the closest Saturn moons, well below typical screen pixel scale.
// Verified manually: 0.1 results in visible flickery offset from moons to their trails.
const TRAIL_CURVE_REFRESH_DEG = 0.01;

// Re-snapshot chebyshev-derived osculating elements after sim jd has advanced
// by this fraction of the orbit's period. Bounds the body-on-curve drift that
// accumulates when the static snapshot ages — Earth's Moon (period ~28 d)
// re-derives every ~0.28 d of sim time, Pluto every ~2.5 yr.
const CHEB_ELEMENTS_REFRESH_PERIOD_FRACTION = 1 / 100;
// Hard cap on the re-derive cadence so long-period bodies still refresh in
// reasonable sim time. Mostly matters for probe trails: a Voyager-style cruise
// modeled as a heliocentric Kepler-pure sub-chunk has period ~years, and the
// curve needs to rebuild within hours of crossing into a Chebyshev sub-chunk
// at a planetary flyby — not months. Benign for existing bodies (Pluto's 2.5 yr
// gate becomes 1 d; Earth's Moon's 0.28 d gate is already tighter).
const MAX_REDERIVE_DAYS = 1.0;

/**
 * Rewrite a buffer-backed trail's vertex buffer from its current contents.
 * Called from {@link refreshTrail} per jd tick and from focus-change paths.
 * Unlike the Kepler/SGP4 path, there's no cached vertex list to rebase — the
 * ring buffer is the source of truth, so we just re-read it with the new basis.
 */
export function refreshBufferTrail(
	body: PositionedBody,
	line: Line | Mesh,
	buffer: TrailBuffer,
	basisPos: [number, number, number]
): void {
	const useTrail = line.userData.useTrail as boolean;
	const oc = line.userData.orbitCenter as Vector3;
	const { posArr, trailArr, fullArr } = getTrailWorkingArrays(line);
	const total = writeBufferVerticesWithLiveHead(body, buffer, posArr, oc.x, oc.y, oc.z, basisPos);
	commitTrail(line, posArr, trailArr, fullArr, total, true, useTrail);
}

/**
 * Rewrite a trail's vertex buffer from cached orbit-local positions and
 * a fresh basis offset, without any curve recompute. Used by the focus-change
 * path, which needs every line rebased before the first render against the new
 * basis but does not advance jd.
 */
export function rebaseTrailLocals(
	line: Line | Mesh,
	localPositions: [number, number, number][],
	ox: number,
	oy: number,
	oz: number
): void {
	const { posArr, trailArr, fullArr, capacity } = getTrailWorkingArrays(line);
	const n = Math.min(localPositions.length, capacity);
	for (let i = 0; i < n; i++) {
		posArr[i * 3] = localPositions[i][0] + ox;
		posArr[i * 3 + 1] = localPositions[i][1] + oy;
		posArr[i * 3 + 2] = localPositions[i][2] + oz;
	}
	if (line.userData.isFatLine) {
		writeFatTrailVertices(line.geometry, posArr, trailArr, fullArr, n);
		return;
	}
	line.geometry.getAttribute('position').needsUpdate = true;
}

/**
 * Re-anchor a trail at the body's current position. Must run after the body
 * (and its `orbitCenter`) have been updated this frame.
 *
 * For SGP4-backed bodies, the underlying curve is regenerated each call using
 * `jd` so the trail always represents the past orbital period up to the sim
 * clock — a static construction-time curve would drift out of sync under time
 * playback (and go stale entirely under drag/J2 secular effects).
 */
export function refreshTrail(
	body: PositionedBody,
	line: Line | Mesh,
	basisPos: [number, number, number],
	jd: number
): void {
	// Trail-buffer path: buffer holds live past-position samples maintained by
	// `updatePositions`; just copy them into the vertex buffer shifted by
	// (orbitCenter − basis). No curve cache to fall back on, so this branch
	// must run before the early-return on missing `sourceCurve`.
	const trailBuffer = line.userData.trailBuffer as TrailBuffer | undefined;
	if (trailBuffer) {
		refreshBufferTrail(body, line, trailBuffer, basisPos);
		return;
	}

	let curve = line.userData.sourceCurve as [number, number, number][] | undefined;
	if (!curve) return;
	const isOpenCurve = line.userData.isOpenCurve as boolean;
	const useTrail = line.userData.useTrail as boolean;
	const oc = line.userData.orbitCenter as Vector3;
	const cx = oc.x,
		cy = oc.y,
		cz = oc.z;

	// SGP4 curves are a sliding window ending at the current sim jd.
	if (body.data.satrec) {
		curve = sgp4Curve(body.data.satrec, jd, body.data.n / 360, NUM_TRAIL_POINTS);
		line.userData.sourceCurve = curve;
	} else if (body.orbitElements) {
		// Chebyshev-derived osculating elements: re-snapshot periodically so
		// the static ellipse stays aligned with the body's actual chebyshev
		// path. Mutates `body.orbitElements` in place so other PositionedBodies
		// sharing the ref (e.g. a planet borrowing its barycenter's elements)
		// see the update too.
		if (body.rederiveElements) {
			const elementsJd = (line.userData.elementsJd as number | undefined) ?? jd;
			const n = body.orbitElements.n;
			const period = n > 0 ? 360 / n : Infinity;
			const dt = Math.abs(jd - elementsJd);
			const refreshThreshold = Math.min(
				period * CHEB_ELEMENTS_REFRESH_PERIOD_FRACTION,
				MAX_REDERIVE_DAYS
			);
			if (dt > refreshThreshold) {
				const fresh = body.rederiveElements(jd);
				// Null fresh = jd out of chebyshev coverage; the body's
				// out-of-range toast already surfaces that, so we silently
				// keep the stale snapshot rather than warn-spamming per frame.
				if (fresh) {
					Object.assign(body.orbitElements, fresh);
					curve = orbitalElementsToCurve(body.orbitElements, NUM_TRAIL_POINTS).points;
					line.userData.sourceCurve = curve;
					line.userData.curveJd = jd;
					line.userData.elementsJd = jd;
				}
			}
		}
		// Method-C-fit moons carry secular Ω/ω drift; the curve was built with
		// angles current at construction time but goes stale as `jd` advances.
		// Regenerate when the predicted angular drift since the last build
		// exceeds TRAIL_CURVE_REFRESH_DEG — gated to avoid per-frame work for
		// slow precessors where drift takes years to accumulate. No-op for
		// chebyshev-derived elements since those don't carry omDot/wDot.
		const omDot = body.orbitElements.omDot ?? 0;
		const wDot = body.orbitElements.wDot ?? 0;
		const maxRate = Math.max(Math.abs(omDot), Math.abs(wDot));
		if (maxRate > 0) {
			const curveJd = (line.userData.curveJd as number | undefined) ?? jd;
			if (maxRate * Math.abs(jd - curveJd) > TRAIL_CURVE_REFRESH_DEG) {
				const propagated = propagateOrbitAngles(body.orbitElements, jd);
				curve = orbitalElementsToCurve(propagated, NUM_TRAIL_POINTS).points;
				line.userData.sourceCurve = curve;
				line.userData.curveJd = jd;
			}
		}
	}

	// Memoization gate: when curve, anchor, orbit-center, and basis are all
	// unchanged since the last commit, the vertex buffer is still correct.
	// Skip nearest-point search + buffer rewrite — meaningful during paused
	// camera drags where everything is static but rAF still fires.
	const anchor = body.trailAnchor ?? body.position;
	const ud = line.userData;
	const curveChanged = curve !== ud.lastCurveRef;
	const anchorChanged =
		anchor[0] !== ud.lastAnchorX || anchor[1] !== ud.lastAnchorY || anchor[2] !== ud.lastAnchorZ;
	const centerChanged = cx !== ud.lastCenterX || cy !== ud.lastCenterY || cz !== ud.lastCenterZ;
	const basisChanged =
		basisPos[0] !== ud.lastBasisX || basisPos[1] !== ud.lastBasisY || basisPos[2] !== ud.lastBasisZ;
	if (!curveChanged && !anchorChanged && !centerChanged && !basisChanged) return;

	const validPoints = buildTrailPoints(body, curve, isOpenCurve, cx, cy, cz);
	if (validPoints.length < 2) return;

	// Clamp to working-array capacity rather than silently skipping — dropping
	// a frame from a too-small buffer would freeze the trail permanently when
	// the SGP4 window grows past its construction-time size.
	const { posArr, trailArr, fullArr, capacity } = getTrailWorkingArrays(line);
	const bx = cx - basisPos[0],
		by = cy - basisPos[1],
		bz = cz - basisPos[2];
	const n = Math.min(validPoints.length, capacity);
	for (let k = 0; k < n; k++) {
		posArr[k * 3] = validPoints[k][0] + bx;
		posArr[k * 3 + 1] = validPoints[k][1] + by;
		posArr[k * 3 + 2] = validPoints[k][2] + bz;
	}
	commitTrail(line, posArr, trailArr, fullArr, n, isOpenCurve, useTrail);
	// Cache the new orbit-local vertex list for the next focus-basis rebuild.
	ud.trailLocalPositions = validPoints;
	ud.lastCurveRef = curve;
	ud.lastAnchorX = anchor[0];
	ud.lastAnchorY = anchor[1];
	ud.lastAnchorZ = anchor[2];
	ud.lastCenterX = cx;
	ud.lastCenterY = cy;
	ud.lastCenterZ = cz;
	ud.lastBasisX = basisPos[0];
	ud.lastBasisY = basisPos[1];
	ud.lastBasisZ = basisPos[2];
}
