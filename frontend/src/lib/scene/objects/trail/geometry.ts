import {
	BufferGeometry,
	Float32BufferAttribute,
	Line,
	Mesh,
	ShaderMaterial,
	Uint16BufferAttribute
} from 'three';
import { makeFatTrailMaterial, makeTrailMaterial } from './material';
import { writeTrailAlphas } from './points';

/**
 * Build the indexed triangle geometry backing a fat trail. Vertices come
 * in side pairs (one shifted to `-1`, one to `+1` perpendicular to the segment
 * in screen space); the index buffer is pre-filled with `(capacity - 1)` quads.
 *
 * Refresh paths populate the per-vertex arrays via {@link writeFatTrailVertices}
 * and call `geometry.setDrawRange(0, 6 * (n - 1))` to control how many quads
 * render.
 */
export function makeFatTrailGeometry(capacity: number): BufferGeometry {
	const vertCount = 2 * capacity;
	const positions = new Float32Array(vertCount * 3);
	const nextPositions = new Float32Array(vertCount * 3);
	const sides = new Float32Array(vertCount);
	const trailAlphas = new Float32Array(vertCount);
	const fullAlphas = new Float32Array(vertCount);
	for (let i = 0; i < capacity; i++) {
		sides[2 * i] = -1;
		sides[2 * i + 1] = 1;
	}
	const indices = new Uint16Array(Math.max(0, 6 * (capacity - 1)));
	for (let i = 0; i < capacity - 1; i++) {
		const a = 2 * i;
		const b = 2 * i + 1;
		const c = 2 * (i + 1);
		const d = 2 * (i + 1) + 1;
		const o = i * 6;
		indices[o] = a;
		indices[o + 1] = b;
		indices[o + 2] = c;
		indices[o + 3] = c;
		indices[o + 4] = b;
		indices[o + 5] = d;
	}

	const geometry = new BufferGeometry();
	geometry.setAttribute('position', new Float32BufferAttribute(positions, 3));
	geometry.setAttribute('nextPosition', new Float32BufferAttribute(nextPositions, 3));
	geometry.setAttribute('side', new Float32BufferAttribute(sides, 1));
	geometry.setAttribute('trailAlpha', new Float32BufferAttribute(trailAlphas, 1));
	geometry.setAttribute('fullAlpha', new Float32BufferAttribute(fullAlphas, 1));
	geometry.setIndex(new Uint16BufferAttribute(indices, 1));
	return geometry;
}

/**
 * Populate a fat trail's vertex arrays from `n` logical points + alpha
 * ramps. Each point is duplicated into a (-1, +1) side pair; `nextPosition`
 * for the last point falls back to itself so the shader's degenerate-segment
 * branch picks a stable perpendicular.
 */
export function writeFatTrailVertices(
	geometry: BufferGeometry,
	posSrc: Float32Array,
	trailSrc: Float32Array,
	fullSrc: Float32Array,
	n: number
): void {
	const posAttr = geometry.getAttribute('position');
	const nextAttr = geometry.getAttribute('nextPosition');
	const trailAttr = geometry.getAttribute('trailAlpha');
	const fullAttr = geometry.getAttribute('fullAlpha');
	const posArr = posAttr.array as Float32Array;
	const nextArr = nextAttr.array as Float32Array;
	const trailArr = trailAttr.array as Float32Array;
	const fullArr = fullAttr.array as Float32Array;
	const cap = trailArr.length / 2;
	const m = Math.min(n, cap);
	for (let i = 0; i < m; i++) {
		const px = posSrc[i * 3];
		const py = posSrc[i * 3 + 1];
		const pz = posSrc[i * 3 + 2];
		const nextI = i < m - 1 ? i + 1 : i;
		const nx = posSrc[nextI * 3];
		const ny = posSrc[nextI * 3 + 1];
		const nz = posSrc[nextI * 3 + 2];
		const baseA = 2 * i * 3;
		posArr[baseA] = px;
		posArr[baseA + 1] = py;
		posArr[baseA + 2] = pz;
		posArr[baseA + 3] = px;
		posArr[baseA + 4] = py;
		posArr[baseA + 5] = pz;
		nextArr[baseA] = nx;
		nextArr[baseA + 1] = ny;
		nextArr[baseA + 2] = nz;
		nextArr[baseA + 3] = nx;
		nextArr[baseA + 4] = ny;
		nextArr[baseA + 5] = nz;
		const tA = trailSrc[i];
		const fA = fullSrc[i];
		trailArr[2 * i] = tA;
		trailArr[2 * i + 1] = tA;
		fullArr[2 * i] = fA;
		fullArr[2 * i + 1] = fA;
	}
	posAttr.needsUpdate = true;
	nextAttr.needsUpdate = true;
	trailAttr.needsUpdate = true;
	fullAttr.needsUpdate = true;
	geometry.setDrawRange(0, Math.max(0, 6 * (m - 1)));
}

export function makeEmptyTrail(): Line | Mesh {
	const geometry = new BufferGeometry();
	geometry.setAttribute('position', new Float32BufferAttribute(new Float32Array(6), 3));
	const material = new ShaderMaterial({ transparent: true });
	const line = new Line(geometry, material);
	line.visible = false;
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
	return new Line(geometry, makeTrailMaterial(color));
}

/** Wrap pre-computed thin arrays into a fat-line `Mesh`. */
export function buildFatLineFromThin(
	capacity: number,
	posArr: Float32Array,
	trailAlphas: Float32Array,
	fullAlphas: Float32Array,
	total: number,
	color: string,
	lineWidth: number
): Mesh {
	const geometry = makeFatTrailGeometry(capacity);
	writeFatTrailVertices(geometry, posArr, trailAlphas, fullAlphas, total);
	return new Mesh(geometry, makeFatTrailMaterial(color, lineWidth));
}

/**
 * Working arrays for the per-frame trail refresh. For thin `Line` objects this
 * is the live geometry attribute backing storage; for fat `Mesh` objects it is
 * the userData scratch that {@link writeFatTrailVertices} later expands into
 * the duplicated/indexed geometry. `capacity` is logical points (the fat
 * geometry has 2× that many vertices, but the writer accepts logical counts).
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
 * Finish a trail refresh: compute alpha ramps, then either expand into the
 * fat-line geometry or mark the thin-line attrs dirty and set the draw range.
 * `n < 2` collapses the line to draw nothing. Both refresh paths (chebyshev
 * buffer, Kepler/SGP4 curve) populate `posArr` with their own logic and call
 * this to commit the frame's geometry update.
 */
export function commitTrail(
	line: Line | Mesh,
	posArr: Float32Array,
	trailArr: Float32Array,
	fullArr: Float32Array,
	n: number,
	isOpenCurve: boolean,
	useTrail: boolean
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
		isOpenCurve,
		useTrail
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
