import {
	BufferGeometry,
	Float32BufferAttribute,
	InstancedBufferGeometry,
	InstancedInterleavedBuffer,
	InterleavedBufferAttribute,
	Line,
	Mesh,
	ShaderMaterial
} from 'three';
import { makeFatTrailMaterial, makeTrailMaterial } from './material';
import { writeTrailAlphas } from './points';

// Draw order alone decides overlap between these depthWrite=false layers: after
// the cloud sphere so its dark side doesn't dim trails, and after point clouds
// (POINT_CLOUD_RENDER_ORDER) so trails draw over the dots.
const TRAIL_RENDER_ORDER = 3;

/** A fat line segment's quad: each corner's side of the line (±1) and end
 *  (0 at the segment's start, 1 at its end). */
const QUAD_CORNERS = [-1, 0, 1, 0, -1, 1, 1, 1];
const QUAD_INDICES = [0, 1, 2, 2, 1, 3];

/** The instanced buffer behind a fat line's attribute `name`. */
function instanced(geometry: BufferGeometry, name: string): InstancedInterleavedBuffer {
	return (geometry.getAttribute(name) as InterleavedBufferAttribute)
		.data as InstancedInterleavedBuffer;
}

/** Two attributes on one buffer of `stride` floats a point: a segment's start
 *  point, and its end, read one point further on. */
function setSegmentAttributes(
	geometry: BufferGeometry,
	names: [string, string],
	capacity: number,
	stride: number
): void {
	const buffer = new InstancedInterleavedBuffer(new Float32Array(capacity * stride), stride);
	geometry.setAttribute(names[0], new InterleavedBufferAttribute(buffer, stride, 0));
	geometry.setAttribute(names[1], new InterleavedBufferAttribute(buffer, stride, stride));
}

/**
 * Geometry for a fat line of up to `capacity` points, one instance per segment:
 * a quad the shader widens on screen and cuts at the camera, which it can only
 * do with both ends of a segment in hand. The quad is the geometry's own, since
 * disposing a geometry deletes the GL buffers of all its attributes. Refresh
 * paths fill the points via {@link writeFatTrailVertices}.
 */
export function makeFatTrailGeometry(capacity: number): InstancedBufferGeometry {
	const geometry = new InstancedBufferGeometry();
	geometry.setAttribute('corner', new Float32BufferAttribute(QUAD_CORNERS, 2));
	geometry.setIndex(QUAD_INDICES);
	setSegmentAttributes(geometry, ['segStart', 'segEnd'], capacity, 3);
	// Trail alpha then full alpha, for each point.
	setSegmentAttributes(geometry, ['alphaStart', 'alphaEnd'], capacity, 2);
	geometry.instanceCount = 0;
	return geometry;
}

/** Fill a fat line with `n` points and their alpha ramps. */
export function writeFatTrailVertices(
	geometry: BufferGeometry,
	posSrc: Float32Array,
	trailSrc: Float32Array,
	fullSrc: Float32Array,
	n: number
): void {
	const points = instanced(geometry, 'segStart');
	const alphas = instanced(geometry, 'alphaStart');
	const m = Math.min(n, points.count);
	(points.array as Float32Array).set(posSrc.subarray(0, m * 3));
	const alphaArr = alphas.array as Float32Array;
	for (let i = 0; i < m; i++) {
		alphaArr[2 * i] = trailSrc[i];
		alphaArr[2 * i + 1] = fullSrc[i];
	}
	points.needsUpdate = true;
	alphas.needsUpdate = true;
	// Each instance reads its end one point on, so the last point starts none.
	(geometry as InstancedBufferGeometry).instanceCount = Math.max(0, m - 1);
	// commitTrail empties the range for a line too short to draw.
	geometry.setDrawRange(0, QUAD_INDICES.length);
}

export function makeEmptyTrail(): Line | Mesh {
	const geometry = new BufferGeometry();
	geometry.setAttribute('position', new Float32BufferAttribute(new Float32Array(6), 3));
	const material = new ShaderMaterial({ transparent: true });
	const line = new Line(geometry, material);
	// Vertices are written focus-relative; the object itself never moves.
	line.matrixAutoUpdate = false;
	line.visible = false;
	line.renderOrder = TRAIL_RENDER_ORDER;
	return line;
}

/** Wrap pre-computed thin arrays into a `Line` with a shared trail material. */
export function buildThinLineFromArrays(
	posArr: Float32Array,
	trailAlphas: Float32Array,
	fullAlphas: Float32Array,
	total: number,
	color: string
): Line {
	const geometry = new BufferGeometry();
	geometry.setAttribute('position', new Float32BufferAttribute(posArr, 3));
	geometry.setAttribute('trailAlpha', new Float32BufferAttribute(trailAlphas, 1));
	geometry.setAttribute('fullAlpha', new Float32BufferAttribute(fullAlphas, 1));
	geometry.setDrawRange(0, total);
	const line = new Line(geometry, makeTrailMaterial(color));
	line.matrixAutoUpdate = false;
	line.renderOrder = TRAIL_RENDER_ORDER;
	return line;
}

/** A dashed fat line's length along itself to each of its `n` points. */
export function writeLineDistances(geometry: BufferGeometry, src: Float32Array, n: number): void {
	const distances = instanced(geometry, 'distStart');
	(distances.array as Float32Array).set(src.subarray(0, Math.min(n, distances.count)));
	distances.needsUpdate = true;
}

/** Wrap pre-computed thin arrays into a fat-line `Mesh`. `brightness` defaults
 *  to the shade orbit trails are drawn at, and `dash` to a solid line; see
 *  {@link makeFatTrailMaterial}. */
export function buildFatLineFromThin(
	capacity: number,
	posArr: Float32Array,
	trailAlphas: Float32Array,
	fullAlphas: Float32Array,
	total: number,
	color: string,
	lineWidth: number,
	brightness?: number,
	dash?: readonly [number, number]
): Mesh {
	const geometry = makeFatTrailGeometry(capacity);
	if (dash) setSegmentAttributes(geometry, ['distStart', 'distEnd'], capacity, 1);
	writeFatTrailVertices(geometry, posArr, trailAlphas, fullAlphas, total);
	const mesh = new Mesh(geometry, makeFatTrailMaterial(color, lineWidth, brightness, dash));
	mesh.matrixAutoUpdate = false;
	mesh.renderOrder = TRAIL_RENDER_ORDER;
	return mesh;
}

/**
 * Working arrays for per-frame trail refresh: live geometry attributes for
 * thin `Line`s, userData scratch for fat `Mesh`es (copied in by
 * {@link writeFatTrailVertices}). `capacity` is in points.
 */
export function getTrailWorkingArrays(line: Line | Mesh): {
	posArr: Float32Array;
	trailArr: Float32Array;
	fullArr: Float32Array;
	capacity: number;
} {
	if (line.userData.isFatLine) {
		const posArr = line.userData.thinPositions as Float32Array;
		return {
			posArr,
			trailArr: line.userData.thinTrailAlphas as Float32Array,
			fullArr: line.userData.thinFullAlphas as Float32Array,
			capacity: posArr.length / 3
		};
	}
	const posAttr = line.geometry.getAttribute('position');
	return {
		posArr: posAttr.array as Float32Array,
		trailArr: line.geometry.getAttribute('trailAlpha').array as Float32Array,
		fullArr: line.geometry.getAttribute('fullAlpha').array as Float32Array,
		capacity: posAttr.count
	};
}

/**
 * Finish a trail refresh: compute alpha ramps, then write them into the fat
 * line or mark thin-line attrs dirty. `n < 2` draws nothing. Both refresh
 * paths (chebyshev buffer, Kepler/SGP4 curve) call this after filling `posArr`.
 */
export function commitTrail(
	line: Line | Mesh,
	posArr: Float32Array,
	trailArr: Float32Array,
	fullArr: Float32Array,
	n: number,
	isOpenCurve: boolean,
	useTrail: boolean,
	trailReach?: number
): void {
	if (n < 2) {
		line.geometry.setDrawRange(0, 0);
		if (!line.userData.isFatLine) {
			line.geometry.getAttribute('position').needsUpdate = true;
		}
		return;
	}
	writeTrailAlphas(
		fullArr.subarray(0, n) as Float32Array,
		trailArr.subarray(0, n) as Float32Array,
		posArr,
		isOpenCurve,
		useTrail,
		trailReach
	);
	if (line.userData.isFatLine) {
		writeFatTrailVertices(line.geometry, posArr, trailArr, fullArr, n);
		return;
	}
	line.geometry.setDrawRange(0, n);
	line.geometry.getAttribute('position').needsUpdate = true;
	line.geometry.getAttribute('trailAlpha').needsUpdate = true;
	line.geometry.getAttribute('fullAlpha').needsUpdate = true;
}
