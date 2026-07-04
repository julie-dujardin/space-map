import { Line, Mesh, Vector3 } from 'three';
import { orbitalElementsToCurve, sgp4Curve } from '$lib/math/orbit/curves';
import { propagateOrbitAngles } from '$lib/math/orbit/position';
import { dateToJD } from '$lib/format/date';
import { ObjectType, isAsteroid, type PositionedBody } from '$lib/types/objects';
import type { TrailBuffer } from '$lib/fetch/position/trail-buffer';
import { NUM_TRAIL_POINTS, buildTrailPoints, writeTrailAlphas } from './points';
import { buildFatLineFromThin, buildThinLineFromArrays, makeEmptyTrail } from './geometry';

/**
 * Write a trail-buffer's contents into `posArr`, prefixed by a "live head"
 * vertex at the body's current position. The +1 slot keeps the brightest
 * trail vertex on the body itself — the same anchor the Kepler-curve path
 * gets for free via `points[0] = bodyLocal`. Buffer samples are
 * fit-center-relative, so they're shifted by `(orbitCenter − basis)`.
 */
export function writeBufferVerticesWithLiveHead(
	body: PositionedBody,
	buffer: TrailBuffer,
	posArr: Float32Array,
	cx: number,
	cy: number,
	cz: number,
	basisPos: [number, number, number]
): number {
	const head = body.trailAnchor ?? body.position;
	posArr[0] = head[0] - basisPos[0];
	posArr[1] = head[1] - basisPos[1];
	posArr[2] = head[2] - basisPos[2];
	const bx = cx - basisPos[0];
	const by = cy - basisPos[1];
	const bz = cz - basisPos[2];
	const n = buffer.writeVertices(posArr.subarray(3) as Float32Array, bx, by, bz);
	return 1 + n;
}

/**
 * Build a trail backed by a sample buffer. Geometry is sized to `capacity + 1` —
 * the +1 slot holds the live body position so the brightest trail vertex
 * always sits on the body. Used for probes whose chunk has at least one
 * chebyshev sub-chunk: an osculating-Kepler ellipse misrepresents the path
 * during a flyby or capture, so we polyline the actual past trajectory.
 */
function makeBufferTrail(
	body: PositionedBody,
	trailBuffer: TrailBuffer,
	color: string,
	basisPos: [number, number, number],
	lineWidth: number
): Line | Mesh {
	const { orbitCenter, data } = body;
	const cx = orbitCenter?.[0] ?? 0;
	const cy = orbitCenter?.[1] ?? 0;
	const cz = orbitCenter?.[2] ?? 0;

	const useTrail =
		data.objectType === ObjectType.SPACECRAFT ||
		data.objectType === ObjectType.DWARF_PLANET ||
		data.objectType === ObjectType.MOON ||
		data.objectType === ObjectType.COMET ||
		isAsteroid(data.objectType);

	const geomCap = trailBuffer.capacity + 1;
	const posArr = new Float32Array(geomCap * 3);
	const total = writeBufferVerticesWithLiveHead(body, trailBuffer, posArr, cx, cy, cz, basisPos);

	const fullAlphas = new Float32Array(geomCap);
	const trailAlphas = new Float32Array(geomCap);
	if (total > 0) {
		writeTrailAlphas(
			fullAlphas.subarray(0, total) as Float32Array,
			trailAlphas.subarray(0, total) as Float32Array,
			true,
			useTrail
		);
	}

	const isFat = lineWidth > 1;
	const obj = isFat
		? buildFatLineFromThin(geomCap, posArr, trailAlphas, fullAlphas, total, color, lineWidth)
		: buildThinLineFromArrays(posArr, trailAlphas, fullAlphas, total, color);

	obj.frustumCulled = false;
	obj.visible = false;
	obj.userData.orbitCenter = new Vector3(cx, cy, cz);
	obj.userData.trailBuffer = trailBuffer;
	obj.userData.useTrail = useTrail;
	if (isFat) {
		obj.userData.isFatLine = true;
		obj.userData.thinPositions = posArr;
		obj.userData.thinTrailAlphas = trailAlphas;
		obj.userData.thinFullAlphas = fullAlphas;
	}
	return obj;
}

export function makeTrail(
	body: PositionedBody,
	color: string,
	basisPos: [number, number, number] = [0, 0, 0],
	jd: number = dateToJD(new Date()),
	lineWidth: number = 1
): Line | Mesh {
	if (body.trailBuffer) {
		return makeBufferTrail(body, body.trailBuffer, color, basisPos, lineWidth);
	}
	const { orbitElements, orbitCenter, data } = body;

	// SGP4 Earth sats: sample the propagator over the past period so the trail
	// ends on the body (data.n is deg/day here, hence /360 back to rev/day).
	// Kept open: a sliding window never rejoins curve[0] to the body, so closing
	// it draws a stray segment that spikes off the marker up close.
	let curve: [number, number, number][];
	let isOpenCurve: boolean;
	if (data.satrec) {
		curve = sgp4Curve(data.satrec, jd, data.n / 360, NUM_TRAIL_POINTS);
		isOpenCurve = true;
	} else {
		if (!orbitElements) throw new Error('makeTrail called without orbitElements');
		// Apply secular drift on Ω/ω so the drawn ellipse matches the body's
		// current orbit plane, not the chunk midpoint's. The curve is re-rendered
		// from refreshTrail once accumulated drift exceeds TRAIL_CURVE_REFRESH_DEG;
		// the curveJd anchor below is its starting point.
		const propagated = propagateOrbitAngles(orbitElements, jd);
		const result = orbitalElementsToCurve(propagated, NUM_TRAIL_POINTS);
		curve = result.points;
		isOpenCurve = result.isOpen;
	}

	const cx = orbitCenter?.[0] ?? 0;
	const cy = orbitCenter?.[1] ?? 0;
	const cz = orbitCenter?.[2] ?? 0;

	const useTrail =
		isOpenCurve ||
		data.objectType === ObjectType.DWARF_PLANET ||
		data.objectType === ObjectType.MOON ||
		data.objectType === ObjectType.SPACECRAFT ||
		data.objectType === ObjectType.COMET ||
		isAsteroid(data.objectType);

	const validPoints = buildTrailPoints(body, curve, isOpenCurve, cx, cy, cz);
	if (validPoints.length < 2) return makeEmptyTrail();

	// Size buffers to the full curve length so refreshes that produce longer
	// trails (e.g. body.position and curve become consistent after the first
	// tick for SGP4 bodies) don't hit the `posAttr.count < validPoints.length`
	// early-return in refreshTrail.
	const bufferCapacity = Math.max(validPoints.length, curve.length);
	const fullAlphas = new Float32Array(bufferCapacity);
	const trailAlphas = new Float32Array(bufferCapacity);
	writeTrailAlphas(
		fullAlphas.subarray(0, validPoints.length) as Float32Array,
		trailAlphas.subarray(0, validPoints.length) as Float32Array,
		isOpenCurve,
		useTrail
	);

	// Store vertices in basis-relative coords (world − basis). Basis tracks
	// the focused body, so for focused bodies the vertex magnitudes stay
	// small and the shader's (vertex + uCenterOffset) avoids catastrophic
	// Float32 cancellation even for distant outer-solar-system bodies.
	const bx = cx - basisPos[0],
		by = cy - basisPos[1],
		bz = cz - basisPos[2];
	const posArr = new Float32Array(bufferCapacity * 3);
	for (let k = 0; k < validPoints.length; k++) {
		posArr[k * 3] = validPoints[k][0] + bx;
		posArr[k * 3 + 1] = validPoints[k][1] + by;
		posArr[k * 3 + 2] = validPoints[k][2] + bz;
	}

	const isFat = lineWidth > 1;
	const obj = isFat
		? buildFatLineFromThin(
				bufferCapacity,
				posArr,
				trailAlphas,
				fullAlphas,
				validPoints.length,
				color,
				lineWidth
			)
		: buildThinLineFromArrays(posArr, trailAlphas, fullAlphas, validPoints.length, color);
	obj.frustumCulled = false; // shader repositions geometry via uCenterOffset
	obj.visible = false; // updateBodyVisibility sets the correct state next frame; avoids a 1-frame flash when added mid-load
	// Store Float64 orbit-local positions for rebuilding when focus changes,
	// and the static curve + flags for per-frame trail refresh while time plays.
	obj.userData.orbitCenter = new Vector3(cx, cy, cz);
	obj.userData.trailLocalPositions = validPoints;
	obj.userData.sourceCurve = curve;
	obj.userData.isOpenCurve = isOpenCurve;
	obj.userData.useTrail = useTrail;
	obj.userData.curveJd = jd;
	// Last jd at which `body.orbitElements` was snapshot — read by the
	// chebyshev re-derive gate in refreshTrail. Defaults to the elements' own
	// epoch (chebyshev callers set epoch to derive-jd); non-rederive bodies
	// don't read it.
	obj.userData.elementsJd = orbitElements?.epoch ?? jd;
	if (isFat) {
		obj.userData.isFatLine = true;
		obj.userData.thinPositions = posArr;
		obj.userData.thinTrailAlphas = trailAlphas;
		obj.userData.thinFullAlphas = fullAlphas;
	}
	return obj;
}
