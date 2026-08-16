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
// even for the closest Saturn moons, well under screen pixel scale.
const TRAIL_CURVE_REFRESH_DEG = 0.01;

// Re-snapshot chebyshev-derived osculating elements after sim jd advances
// this fraction of the orbit's period — bounds drift as the snapshot ages
// (Earth's Moon re-derives every ~0.28 d of sim time, Pluto every ~2.5 yr).
const CHEB_ELEMENTS_REFRESH_PERIOD_FRACTION = 1 / 100;
// Hard cap on re-derive cadence for long-period bodies: a Voyager-style
// heliocentric cruise has a period of years, but must rebuild within hours
// of entering a Chebyshev sub-chunk at a flyby. Benign elsewhere — Pluto's
// gate becomes 1 d, the Moon's 0.28 d gate is already tighter.
const MAX_REDERIVE_DAYS = 1.0;

/**
 * Rewrite a buffer-backed trail's vertex buffer from its current contents.
 * Unlike the Kepler/SGP4 path there's no cached vertex list to rebase — the
 * ring buffer is the source of truth, so this just re-reads it with the new basis.
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
 * Rewrite a trail's vertex buffer from cached orbit-local positions and a
 * fresh basis offset, without a curve recompute — used by the focus-change
 * path, which rebases every line before the next render without advancing jd.
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
 * (and its `orbitCenter`) update this frame.
 *
 * SGP4-backed curves regenerate each call using `jd` so the trail tracks the
 * sim clock — a construction-time curve would drift under time playback and
 * go stale under drag/J2 secular effects.
 */
export function refreshTrail(
	body: PositionedBody,
	line: Line | Mesh,
	basisPos: [number, number, number],
	jd: number
): void {
	// Trail-buffer path: copy `updatePositions`'s live samples into the vertex
	// buffer, shifted by (orbitCenter − basis). Must run before the early-return
	// on missing `sourceCurve` — there's no curve cache to fall back on.
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
		// Chebyshev-derived elements: re-snapshot periodically so the static
		// ellipse stays aligned with the body's real path. Mutates
		// `body.orbitElements` in place so sharers of the ref (e.g. a planet
		// borrowing its barycenter's elements) see the update too.
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
				// Null fresh = jd out of chebyshev coverage; the out-of-range
				// toast already surfaces that, so keep the stale snapshot
				// silently rather than warn-spam per frame.
				if (fresh) {
					Object.assign(body.orbitElements, fresh);
					curve = orbitalElementsToCurve(body.orbitElements, NUM_TRAIL_POINTS).points;
					line.userData.sourceCurve = curve;
					line.userData.curveJd = jd;
					line.userData.elementsJd = jd;
				}
			}
		}
		// Method-C-fit moons carry secular Ω/ω drift, so the curve's build-time
		// angles go stale as `jd` advances. Regenerate once predicted drift
		// exceeds TRAIL_CURVE_REFRESH_DEG — gated to skip slow precessors most
		// frames. No-op for chebyshev elements, which carry no omDot/wDot.
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

	// Memoization gate: skip the nearest-point search + buffer rewrite when
	// curve, anchor, center, and basis are all unchanged — meaningful during
	// paused camera drags where rAF still fires but nothing moved.
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

	// Clamp to working-array capacity rather than skip the frame — skipping
	// would freeze the trail when the SGP4 window outgrows its construction size.
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
