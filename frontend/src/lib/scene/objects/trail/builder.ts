import { Line, Mesh, Vector3 } from 'three';
import { isOpenOrbit, sgp4Curve } from '$lib/math/orbit/curves';
import { ObjectType, isAsteroid, type PositionedBody } from '$lib/types/objects';
import type { TrailBuffer } from '$lib/fetch/position/trail-buffer';
import {
	NUM_TRAIL_POINTS,
	PARTIAL_TRAIL_REACH,
	buildTrailPoints,
	writeTrailAlphas
} from './points';
import { buildFatLineFromThin, buildThinLineFromArrays, makeEmptyTrail } from './geometry';
import type { SampleTransform } from './lagrange-frame';
import { dateToJD } from '$lib/time/jd';
import { renderPixelRatio } from '$lib/scene/render-tier';

/** From this pixel ratio a width-1 trail takes the fat path. A GL line is one
 *  device pixel wide. The low tier caps the ratio below this, so its weak
 *  devices keep the thin line at a fifth of the memory. */
const FAT_TRAIL_MIN_PIXEL_RATIO = 1.5;

function drawsFat(lineWidth: number): boolean {
	return lineWidth > 1 || renderPixelRatio() >= FAT_TRAIL_MIN_PIXEL_RATIO;
}

/** Every open trail draws only the part nearest the body. So do these types. */
function drawsPartialTrail(objectType: ObjectType, isOpenCurve: boolean): boolean {
	return (
		isOpenCurve ||
		objectType === ObjectType.DWARF_PLANET ||
		objectType === ObjectType.MOON ||
		objectType === ObjectType.SPACECRAFT ||
		objectType === ObjectType.COMET ||
		isAsteroid(objectType)
	);
}

/** Share of its length a buffer trail fades over unfocused. An escape trail
 *  is already cut to the length it should show, and a Lagrange trail holds
 *  less than one halo loop. */
export function bufferTrailReach(body: PositionedBody, buffer: TrailBuffer): number {
	return buffer.lengthShare > 0 || body.lagrangeTrail ? 1 : PARTIAL_TRAIL_REACH;
}

/** Cut the polyline in `posArr` to `limit` of length, moving the last vertex
 *  onto the limit so the tip grows smoothly. Returns the vertex count. */
function cutToLength(posArr: Float32Array, n: number, limit: number): number {
	let length = 0;
	for (let k = 1; k < n; k++) {
		const i = k * 3;
		const dx = posArr[i] - posArr[i - 3];
		const dy = posArr[i + 1] - posArr[i - 2];
		const dz = posArr[i + 2] - posArr[i - 1];
		const seg = Math.hypot(dx, dy, dz);
		if (length + seg >= limit) {
			const u = seg > 0 ? (limit - length) / seg : 0;
			posArr[i] = posArr[i - 3] + dx * u;
			posArr[i + 1] = posArr[i - 2] + dy * u;
			posArr[i + 2] = posArr[i - 1] + dz * u;
			return k + 1;
		}
		length += seg;
	}
	return n;
}

/**
 * Write a trail-buffer's contents into `posArr`, prefixed by a live-head
 * vertex at the body's current position — keeps the brightest vertex on the
 * body, same as `points[0] = bodyLocal` for the Kepler path. Samples are
 * fit-center-relative, shifted by `(orbitCenter − basis)`. An escape trail is
 * cut to its share of the head's distance from the centre.
 */
export function writeBufferVerticesWithLiveHead(
	body: PositionedBody,
	buffer: TrailBuffer,
	posArr: Float32Array,
	cx: number,
	cy: number,
	cz: number,
	basisPos: [number, number, number],
	transform?: SampleTransform
): number {
	const head = body.trailAnchor ?? body.position;
	if (!head) return 0;
	posArr[0] = head[0] - basisPos[0];
	posArr[1] = head[1] - basisPos[1];
	posArr[2] = head[2] - basisPos[2];
	const bx = cx - basisPos[0];
	const by = cy - basisPos[1];
	const bz = cz - basisPos[2];
	const n = buffer.writeVertices(posArr.subarray(3) as Float32Array, bx, by, bz, transform);
	if (buffer.lengthShare <= 0) return 1 + n;
	const limit = buffer.lengthShare * Math.hypot(head[0] - cx, head[1] - cy, head[2] - cz);
	return cutToLength(posArr, 1 + n, limit);
}

/**
 * Build a trail backed by a sample buffer, sized `capacity + 1` for the live
 * head vertex. Used when a probe's chunk has a chebyshev sub-chunk — an
 * osculating-Kepler ellipse misrepresents the path during a flyby or capture.
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

	const useTrail = drawsPartialTrail(data.objectType, true);

	const geomCap = trailBuffer.capacity + 1;
	const posArr = new Float32Array(geomCap * 3);
	const total = writeBufferVerticesWithLiveHead(body, trailBuffer, posArr, cx, cy, cz, basisPos);

	const fullAlphas = new Float32Array(geomCap);
	const trailAlphas = new Float32Array(geomCap);
	if (total > 0) {
		writeTrailAlphas(
			fullAlphas.subarray(0, total) as Float32Array,
			trailAlphas.subarray(0, total) as Float32Array,
			posArr,
			true,
			useTrail,
			bufferTrailReach(body, trailBuffer)
		);
	}

	const isFat = drawsFat(lineWidth);
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

	// An SGP4 curve is a window of one period that ends on the body, so the trail
	// starts on its last sample. It is open, because its first sample is not on
	// the body. `data.n` is in deg/day.
	let curve: [number, number, number][] | null;
	let isOpenCurve: boolean;
	let start: number | undefined;
	if (data.satrec) {
		curve = sgp4Curve(data.satrec, jd, data.n / 360, NUM_TRAIL_POINTS);
		isOpenCurve = true;
		start = curve.length - 1;
	} else {
		if (!orbitElements) throw new Error('makeTrail called without orbitElements');
		// The Kepler curve waits for the first refresh that finds the trail
		// visible (see refreshTrail): most of the hundreds built at load never show.
		curve = null;
		isOpenCurve = isOpenOrbit(orbitElements);
	}

	const cx = orbitCenter?.[0] ?? 0;
	const cy = orbitCenter?.[1] ?? 0;
	const cz = orbitCenter?.[2] ?? 0;

	const useTrail = drawsPartialTrail(data.objectType, isOpenCurve);

	const validPoints = curve ? buildTrailPoints(body, curve, isOpenCurve, cx, cy, cz, start) : [];
	if (curve && validPoints.length < 2) return makeEmptyTrail();

	// Size buffers to the full curve length so later refreshes (e.g. SGP4
	// trails growing after the first tick) don't hit refreshTrail's
	// `posAttr.count < validPoints.length` early-return.
	const bufferCapacity = curve ? Math.max(validPoints.length, curve.length) : NUM_TRAIL_POINTS + 1;
	// Store vertices basis-relative (world − basis) so magnitudes stay small
	// near the focused body — avoids Float32 cancellation even for distant
	// outer-solar-system bodies, via the shader's (vertex + uCenterOffset).
	const bx = cx - basisPos[0],
		by = cy - basisPos[1],
		bz = cz - basisPos[2];
	const posArr = new Float32Array(bufferCapacity * 3);
	for (let k = 0; k < validPoints.length; k++) {
		posArr[k * 3] = validPoints[k][0] + bx;
		posArr[k * 3 + 1] = validPoints[k][1] + by;
		posArr[k * 3 + 2] = validPoints[k][2] + bz;
	}

	const fullAlphas = new Float32Array(bufferCapacity);
	const trailAlphas = new Float32Array(bufferCapacity);
	writeTrailAlphas(
		fullAlphas.subarray(0, validPoints.length) as Float32Array,
		trailAlphas.subarray(0, validPoints.length) as Float32Array,
		posArr,
		isOpenCurve,
		useTrail
	);

	const isFat = drawsFat(lineWidth);
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
	// Float64 orbit-local positions for focus-change rebuilds; curve + flags
	// for per-frame refresh while time plays.
	obj.userData.orbitCenter = new Vector3(cx, cy, cz);
	obj.userData.trailLocalPositions = curve ? validPoints : undefined;
	obj.userData.sourceCurve = curve ?? undefined;
	obj.userData.curvePending = curve === null;
	// On a paused clock no pass of the frame loop asks for the curve.
	obj.userData.refreshDeferred = curve === null;
	obj.userData.isOpenCurve = isOpenCurve;
	obj.userData.useTrail = useTrail;
	obj.userData.curveJd = jd;
	// jd `body.orbitElements` was last snapshot — read by refreshTrail's
	// chebyshev re-derive gate. Defaults to the elements' epoch; non-rederive
	// bodies never read it.
	obj.userData.elementsJd = orbitElements?.epoch ?? jd;
	if (isFat) {
		obj.userData.isFatLine = true;
		obj.userData.thinPositions = posArr;
		obj.userData.thinTrailAlphas = trailAlphas;
		obj.userData.thinFullAlphas = fullAlphas;
	}
	return obj;
}
