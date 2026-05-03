import {
	AdditiveBlending,
	BufferAttribute,
	BufferGeometry,
	CanvasTexture,
	Color,
	DoubleSide,
	Float32BufferAttribute,
	Line,
	Mesh,
	Points,
	PointsMaterial,
	ShaderMaterial,
	Sprite,
	SpriteMaterial,
	Uint16BufferAttribute,
	Vector2,
	Vector3
} from 'three';
import { Lensflare, LensflareElement } from 'three/addons/objects/Lensflare.js';
import { orbitalElementsToCurve, sgp4Curve } from '$lib/math/orbit/curves';
import { propagateOrbitAngles } from '$lib/math/orbit/position';
import { dateToJD } from '$lib/format/date';
import { ObjectType, isAsteroid, type PositionedBody } from '$lib/types/objects';
import type { TrailBuffer } from '$lib/fetch/chebyshev/trail-buffer';

export const NUM_ORBIT_POINTS = 512;

// Re-render the precessing-elements curve when accumulated drift on Ω or ω
// exceeds this many degrees. At 0.01° the chord offset stays sub-body-radius
// even for the closest Saturn moons, well below typical screen pixel scale.
// Verified manually: 0.1 results in visible flickery offset from moons to their trails.
const ORBIT_CURVE_REFRESH_DEG = 0.01;

export function makeCircleTexture(): CanvasTexture {
	const size = 32;
	const canvas = document.createElement('canvas');
	canvas.width = size;
	canvas.height = size;
	const ctx = canvas.getContext('2d')!;
	ctx.beginPath();
	ctx.arc(size / 2, size / 2, size / 2 - 2, 0, Math.PI * 2);
	ctx.fillStyle = '#aaaaaa';
	ctx.globalAlpha = 0.3;
	ctx.fill();
	return new CanvasTexture(canvas);
}

/** Anchor the static curve at the body's current position so the trail trails *behind* it. */
function buildOrbitTrailPoints(
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

	const bodyLocal: [number, number, number] = [
		body.position[0] - cx,
		body.position[1] - cy,
		body.position[2] - cz
	];

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
		for (let k = 0; k < NUM_ORBIT_POINTS - 1; k++) {
			const idx = Math.max(trailStart - k, 0);
			points.push(curve[idx]);
			if (idx === 0) break;
		}
	} else {
		for (let k = 0; k < NUM_ORBIT_POINTS - 1; k++) {
			points.push(
				curve[(((trailStart - k) % NUM_ORBIT_POINTS) + NUM_ORBIT_POINTS) % NUM_ORBIT_POINTS]
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
 */
function writeOrbitAlphas(
	fullArr: Float32Array,
	trailArr: Float32Array,
	isOpenCurve: boolean,
	useTrail: boolean
): void {
	const fullMax = 0.9;
	const fullMin = isOpenCurve ? 0 : fullMax / 3;
	const last = fullArr.length - 1;
	for (let k = 0; k < fullArr.length; k++) {
		fullArr[k] = fullMax - (last > 0 ? k / last : 0) * (fullMax - fullMin);
	}
	if (useTrail && !isOpenCurve) {
		const trailLen = Math.round(NUM_ORBIT_POINTS / 3);
		const trailMax = 0.6;
		trailArr.fill(0);
		for (let k = 0; k < Math.min(trailLen, trailArr.length); k++) {
			trailArr[k] = trailMax - (k / (trailLen - 1)) * trailMax;
		}
	} else {
		trailArr.set(fullArr);
	}
}

function makeOrbitLineMaterial(color: string): ShaderMaterial {
	return new ShaderMaterial({
		transparent: true,
		uniforms: {
			uColor: { value: new Color(color) },
			uCenterOffset: { value: new Vector3() },
			uAlphaMultiplier: { value: 1.0 },
			uAlphaMin: { value: 0.0 },
			uShowFull: { value: 0.0 }
		},
		vertexShader: `
			#include <common>
			#include <logdepthbuf_pars_vertex>
			uniform vec3 uCenterOffset;
			uniform float uShowFull;
			attribute float trailAlpha;
			attribute float fullAlpha;
			varying float vAlpha;
			void main() {
				vAlpha = mix(trailAlpha, fullAlpha, uShowFull);
				vec3 relPos = position + uCenterOffset;
				gl_Position = projectionMatrix * vec4(mat3(viewMatrix) * relPos, 1.0);
				#include <logdepthbuf_vertex>
			}
		`,
		fragmentShader: `
			#include <logdepthbuf_pars_fragment>
			uniform vec3 uColor;
			uniform float uAlphaMultiplier;
			uniform float uAlphaMin;
			varying float vAlpha;
			void main() {
				gl_FragColor = vec4(uColor, clamp(max(vAlpha * uAlphaMultiplier, uAlphaMin), 0.0, 1.0));
				#include <logdepthbuf_fragment>
			}
		`
	});
}

// Shared between every fat orbit-line material so resize() updates them all in
// one place. Mutating this Vector2 propagates to every material that holds it
// as a uniform value (Three.js compares by reference, not by snapshot).
const ORBIT_LINE_RESOLUTION = new Vector2(1, 1);

/** Update the screen resolution used by fat orbit lines for screen-space line expansion. */
export function setOrbitLineResolution(width: number, height: number): void {
	ORBIT_LINE_RESOLUTION.set(width, height);
}

/**
 * Fat-line shader: same precision/alpha logic as {@link makeOrbitLineMaterial},
 * but expands each segment to a screen-space quad of width `uLineWidth` pixels.
 *
 * Geometry is indexed triangles built by {@link makeFatOrbitLineGeometry}: each
 * logical point is duplicated into a (-1, +1) side pair, and `nextPosition`
 * carries the segment's other endpoint so the shader can compute screen-space
 * direction without an extra draw call.
 */
function makeFatOrbitLineMaterial(color: string, lineWidth: number): ShaderMaterial {
	return new ShaderMaterial({
		transparent: true,
		side: DoubleSide,
		uniforms: {
			uColor: { value: new Color(color) },
			uCenterOffset: { value: new Vector3() },
			uAlphaMultiplier: { value: 1.0 },
			uAlphaMin: { value: 0.0 },
			uShowFull: { value: 0.0 },
			uLineWidth: { value: lineWidth },
			uResolution: { value: ORBIT_LINE_RESOLUTION }
		},
		vertexShader: `
			#include <common>
			#include <logdepthbuf_pars_vertex>
			uniform vec3 uCenterOffset;
			uniform float uShowFull;
			uniform float uLineWidth;
			uniform vec2 uResolution;
			attribute vec3 nextPosition;
			attribute float side;
			attribute float trailAlpha;
			attribute float fullAlpha;
			varying float vAlpha;
			void main() {
				vAlpha = mix(trailAlpha, fullAlpha, uShowFull);
				vec3 currRel = position + uCenterOffset;
				vec3 nextRel = nextPosition + uCenterOffset;
				vec4 currClip = projectionMatrix * vec4(mat3(viewMatrix) * currRel, 1.0);
				vec4 nextClip = projectionMatrix * vec4(mat3(viewMatrix) * nextRel, 1.0);
				vec2 currNDC = currClip.xy / currClip.w;
				vec2 nextNDC = nextClip.xy / nextClip.w;
				vec2 dirPx = (nextNDC - currNDC) * uResolution * 0.5;
				// Endpoint vertex (or zero-length segment): pick an arbitrary perpendicular
				// so the side pair doesn't collapse onto each other and vanish.
				if (length(dirPx) < 1e-4) dirPx = vec2(1.0, 0.0);
				vec2 dirN = normalize(dirPx);
				vec2 perp = vec2(-dirN.y, dirN.x) * side * uLineWidth * 0.5;
				vec2 offsetNDC = perp / (uResolution * 0.5);
				gl_Position = vec4((currNDC + offsetNDC) * currClip.w, currClip.zw);
				#include <logdepthbuf_vertex>
			}
		`,
		fragmentShader: `
			#include <logdepthbuf_pars_fragment>
			uniform vec3 uColor;
			uniform float uAlphaMultiplier;
			uniform float uAlphaMin;
			varying float vAlpha;
			void main() {
				gl_FragColor = vec4(uColor, clamp(max(vAlpha * uAlphaMultiplier, uAlphaMin), 0.0, 1.0));
				#include <logdepthbuf_fragment>
			}
		`
	});
}

/**
 * Build the indexed triangle geometry backing a fat orbit line. Vertices come
 * in side pairs (one shifted to `-1`, one to `+1` perpendicular to the segment
 * in screen space); the index buffer is pre-filled with `(capacity - 1)` quads.
 *
 * Refresh paths populate the per-vertex arrays via {@link writeFatOrbitVertices}
 * and call `geometry.setDrawRange(0, 6 * (n - 1))` to control how many quads
 * render.
 */
function makeFatOrbitLineGeometry(capacity: number): BufferGeometry {
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
 * Populate a fat orbit line's vertex arrays from `n` logical points + alpha
 * ramps. Each point is duplicated into a (-1, +1) side pair; `nextPosition`
 * for the last point falls back to itself so the shader's degenerate-segment
 * branch picks a stable perpendicular.
 */
function writeFatOrbitVertices(
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

function makeEmptyOrbitLine(): Line | Mesh {
	const geometry = new BufferGeometry();
	geometry.setAttribute('position', new Float32BufferAttribute(new Float32Array(6), 3));
	const material = new ShaderMaterial({ transparent: true });
	const line = new Line(geometry, material);
	line.visible = false;
	return line;
}

/**
 * Write the live "head" vertex (slot 0) and the trail-buffer history (slots
 * 1..n) into `posArr`. Returns the total drawn vertex count.
 *
 * Vertex 0 is always the body's exact current position in basis-relative
 * coords, so the brightest end of the trail stays visually pinned to the
 * body even when the buffer's newest canonical sample is up to one `stepDays`
 * behind `jd`. This is the "point-at-object" anchor the old Kepler-curve
 * path gave for free via `points[0] = bodyLocal`.
 */
function writeBufferVerticesWithLiveHead(
	body: PositionedBody,
	buffer: TrailBuffer,
	posArr: Float32Array,
	cx: number,
	cy: number,
	cz: number,
	basisPos: [number, number, number]
): number {
	// Vertex 0: live parent-relative body position, shifted straight into the
	// basis frame (this is equivalent to `(body.position − orbitCenter) +
	// (orbitCenter − basis)` = `body.position − basis`).
	posArr[0] = body.position[0] - basisPos[0];
	posArr[1] = body.position[1] - basisPos[1];
	posArr[2] = body.position[2] - basisPos[2];

	// Vertices 1..n: buffer samples (parent-relative) shifted by
	// (orbitCenter − basis) so they land in the same basis frame.
	const bx = cx - basisPos[0];
	const by = cy - basisPos[1];
	const bz = cz - basisPos[2];
	const n = buffer.writeVertices(posArr.subarray(3) as Float32Array, bx, by, bz);
	return 1 + n;
}

/**
 * Build a chebyshev-backed orbit line. Geometry is sized to `capacity + 1` —
 * the +1 slot holds the live body position so the brightest trail vertex
 * always sits on the body.
 *
 * When `lineWidth > 1`, the returned object is a `Mesh` of expanded quads
 * instead of a `Line`. The thin position/alpha working arrays still live on
 * `userData` so the per-frame refresh path stays a single shared codepath; the
 * fat geometry is re-derived from them after each update.
 */
function makeChebyshevOrbitLine(
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

	// Moons/dwarfs get a short-fade trail (restored to full when focused);
	// planets/stars get the 360° ramp visible all the time. Matches the
	// existing alpha behaviour for non-chebyshev bodies.
	const useTrail =
		data.objectType === ObjectType.DWARF_PLANET || data.objectType === ObjectType.MOON;

	const geomCap = trailBuffer.capacity + 1;
	const posArr = new Float32Array(geomCap * 3);
	const total = writeBufferVerticesWithLiveHead(body, trailBuffer, posArr, cx, cy, cz, basisPos);

	const fullAlphas = new Float32Array(geomCap);
	const trailAlphas = new Float32Array(geomCap);
	if (total > 0) {
		writeOrbitAlphas(
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

/** Wrap pre-computed thin arrays into a `Line` with a shared orbit-line material. */
function buildThinLineFromArrays(
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
	return new Line(geometry, makeOrbitLineMaterial(color));
}

/** Wrap pre-computed thin arrays into a fat-line `Mesh`. */
function buildFatLineFromThin(
	capacity: number,
	posArr: Float32Array,
	trailAlphas: Float32Array,
	fullAlphas: Float32Array,
	total: number,
	color: string,
	lineWidth: number
): Mesh {
	const geometry = makeFatOrbitLineGeometry(capacity);
	writeFatOrbitVertices(geometry, posArr, trailAlphas, fullAlphas, total);
	return new Mesh(geometry, makeFatOrbitLineMaterial(color, lineWidth));
}

export function makeOrbitLine(
	body: PositionedBody,
	color: string,
	basisPos: [number, number, number] = [0, 0, 0],
	jd: number = dateToJD(new Date()),
	lineWidth: number = 1
): Line | Mesh {
	// Chebyshev-backed: geometry is driven by the rolling trail buffer, which
	// is populated at chunk-load time and advanced each frame by ContextManager.
	if (body.trailBuffer) {
		return makeChebyshevOrbitLine(body, body.trailBuffer, color, basisPos, lineWidth);
	}

	const { orbitElements, orbitCenter, data } = body;

	// SGP4-backed Earth sats: sample the propagator across the *past* orbital
	// period so the trail ends at the body's current position. data.n is in
	// deg/day for SGP4 bodies (converted in chunk.ts); back-convert to rev/day.
	let curve: [number, number, number][];
	let isOpenCurve: boolean;
	if (data.satrec) {
		curve = sgp4Curve(data.satrec, jd, data.n / 360, NUM_ORBIT_POINTS);
		isOpenCurve = true;
	} else {
		if (!orbitElements) throw new Error('makeOrbitLine called without orbitElements');
		// Apply secular drift on Ω/ω so the drawn ellipse matches the body's
		// current orbit plane, not the chunk midpoint's. The curve is re-rendered
		// from refreshOrbitLineGeometry once accumulated drift exceeds
		// ORBIT_CURVE_REFRESH_DEG; the curveJd anchor below is its starting point.
		const propagated = propagateOrbitAngles(orbitElements, jd);
		const result = orbitalElementsToCurve(propagated, NUM_ORBIT_POINTS);
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

	const validPoints = buildOrbitTrailPoints(body, curve, isOpenCurve, cx, cy, cz);
	if (validPoints.length < 2) return makeEmptyOrbitLine();

	// Size buffers to the full curve length so refreshes that produce longer
	// trails (e.g. body.position and curve become consistent after the first
	// tick for SGP4 bodies) don't hit the `posAttr.count < validPoints.length`
	// early-return in refreshOrbitLineGeometry.
	const bufferCapacity = Math.max(validPoints.length, curve.length);
	const fullAlphas = new Float32Array(bufferCapacity);
	const trailAlphas = new Float32Array(bufferCapacity);
	writeOrbitAlphas(
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
	obj.userData.orbitLocalPositions = validPoints;
	obj.userData.orbitCurve = curve;
	obj.userData.isOpenCurve = isOpenCurve;
	obj.userData.useTrail = useTrail;
	obj.userData.curveJd = jd;
	if (isFat) {
		obj.userData.isFatLine = true;
		obj.userData.thinPositions = posArr;
		obj.userData.thinTrailAlphas = trailAlphas;
		obj.userData.thinFullAlphas = fullAlphas;
	}
	return obj;
}

/**
 * Re-anchor an orbit line's trail at the body's current position. Must run
 * after the body (and its `orbitCenter`) have been updated this frame.
 *
 * For SGP4-backed bodies, the underlying curve is regenerated each call using
 * `jd` so the trail always represents the past orbital period up to the sim
 * clock — a static construction-time curve would drift out of sync under time
 * playback (and go stale entirely under drag/J2 secular effects).
 */
/**
 * Rewrite a chebyshev-backed orbit line's vertex buffer from its trail buffer.
 * Called from {@link refreshOrbitLineGeometry} (per jd tick) and from
 * `rebuildOrbitLineBasis` (after focus change without a jd tick). Unlike the
 * Kepler/SGP4 path, there's no cached vertex list to rebase — the ring buffer
 * is already the source of truth, so we just read it again with the new basis.
 */
export function refreshChebyshevOrbitLineGeometry(
	body: PositionedBody,
	line: Line | Mesh,
	buffer: TrailBuffer,
	basisPos: [number, number, number]
): void {
	const useTrail = line.userData.useTrail as boolean;
	const oc = line.userData.orbitCenter as Vector3;

	if (line.userData.isFatLine) {
		// Fat path: write samples + alphas into the thin scratch buffers, then
		// expand into the duplicated/indexed fat geometry. Keeps the buffer
		// read and alpha math identical to the thin path.
		const posArr = line.userData.thinPositions as Float32Array;
		const trailArr = line.userData.thinTrailAlphas as Float32Array;
		const fullArr = line.userData.thinFullAlphas as Float32Array;
		const total = writeBufferVerticesWithLiveHead(body, buffer, posArr, oc.x, oc.y, oc.z, basisPos);
		if (total < 2) {
			line.geometry.setDrawRange(0, 0);
			return;
		}
		writeOrbitAlphas(
			fullArr.subarray(0, total) as Float32Array,
			trailArr.subarray(0, total) as Float32Array,
			true,
			useTrail
		);
		writeFatOrbitVertices(line.geometry, posArr, trailArr, fullArr, total);
		return;
	}

	const posAttr = line.geometry.getAttribute('position');
	const trailAttr = line.geometry.getAttribute('trailAlpha');
	const fullAttr = line.geometry.getAttribute('fullAlpha');
	const posArr = posAttr.array as Float32Array;
	const total = writeBufferVerticesWithLiveHead(body, buffer, posArr, oc.x, oc.y, oc.z, basisPos);
	if (total < 2) {
		line.geometry.setDrawRange(0, 0);
		posAttr.needsUpdate = true;
		return;
	}
	writeOrbitAlphas(
		(fullAttr.array as Float32Array).subarray(0, total) as Float32Array,
		(trailAttr.array as Float32Array).subarray(0, total) as Float32Array,
		true,
		useTrail
	);
	line.geometry.setDrawRange(0, total);
	posAttr.needsUpdate = true;
	trailAttr.needsUpdate = true;
	fullAttr.needsUpdate = true;
}

/**
 * Rewrite an orbit line's vertex buffer from cached orbit-local positions and
 * a fresh basis offset, without any curve recompute. Used by the focus-change
 * path, which needs every line rebased before the first render against the new
 * basis but does not advance jd.
 *
 * Handles both thin `Line` orbit lines (write to position attribute directly)
 * and fat `Mesh` orbit lines (refresh thin scratch arrays then re-expand).
 */
export function rebaseOrbitLineLocals(
	line: Line | Mesh,
	localPositions: [number, number, number][],
	ox: number,
	oy: number,
	oz: number
): void {
	if (line.userData.isFatLine) {
		const posArr = line.userData.thinPositions as Float32Array;
		const trailArr = line.userData.thinTrailAlphas as Float32Array;
		const fullArr = line.userData.thinFullAlphas as Float32Array;
		const cap = posArr.length / 3;
		const n = Math.min(localPositions.length, cap);
		for (let i = 0; i < n; i++) {
			posArr[i * 3] = localPositions[i][0] + ox;
			posArr[i * 3 + 1] = localPositions[i][1] + oy;
			posArr[i * 3 + 2] = localPositions[i][2] + oz;
		}
		writeFatOrbitVertices(line.geometry, posArr, trailArr, fullArr, n);
		return;
	}
	const posAttr = line.geometry.getAttribute('position');
	const arr = posAttr.array as Float32Array;
	for (let i = 0; i < localPositions.length; i++) {
		arr[i * 3] = localPositions[i][0] + ox;
		arr[i * 3 + 1] = localPositions[i][1] + oy;
		arr[i * 3 + 2] = localPositions[i][2] + oz;
	}
	posAttr.needsUpdate = true;
}

export function refreshOrbitLineGeometry(
	body: PositionedBody,
	line: Line | Mesh,
	basisPos: [number, number, number],
	jd: number
): void {
	// Chebyshev-backed: buffer holds live past-position samples; just copy them
	// into the vertex buffer, shifted by (orbitCenter − basis).
	const trailBuffer = line.userData.trailBuffer as TrailBuffer | undefined;
	if (trailBuffer) {
		refreshChebyshevOrbitLineGeometry(body, line, trailBuffer, basisPos);
		return;
	}

	let curve = line.userData.orbitCurve as [number, number, number][] | undefined;
	if (!curve) return;
	const isOpenCurve = line.userData.isOpenCurve as boolean;
	const useTrail = line.userData.useTrail as boolean;
	const oc = line.userData.orbitCenter as Vector3;
	const cx = oc.x,
		cy = oc.y,
		cz = oc.z;

	// SGP4 curves are a sliding window ending at the current sim jd.
	if (body.data.satrec) {
		curve = sgp4Curve(body.data.satrec, jd, body.data.n / 360, NUM_ORBIT_POINTS);
		line.userData.orbitCurve = curve;
	} else if (body.orbitElements) {
		// Method-C-fit moons carry secular Ω/ω drift; the curve was built with
		// angles current at construction time but goes stale as `jd` advances.
		// Regenerate when the predicted angular drift since the last build
		// exceeds ORBIT_CURVE_REFRESH_DEG — gated to avoid per-frame work for
		// slow precessors where drift takes years to accumulate.
		const omDot = body.orbitElements.omDot ?? 0;
		const wDot = body.orbitElements.wDot ?? 0;
		const maxRate = Math.max(Math.abs(omDot), Math.abs(wDot));
		if (maxRate > 0) {
			const curveJd = (line.userData.curveJd as number | undefined) ?? jd;
			if (maxRate * Math.abs(jd - curveJd) > ORBIT_CURVE_REFRESH_DEG) {
				const propagated = propagateOrbitAngles(body.orbitElements, jd);
				curve = orbitalElementsToCurve(propagated, NUM_ORBIT_POINTS).points;
				line.userData.orbitCurve = curve;
				line.userData.curveJd = jd;
			}
		}
	}

	const validPoints = buildOrbitTrailPoints(body, curve, isOpenCurve, cx, cy, cz);
	if (validPoints.length < 2) return;

	const isFat = line.userData.isFatLine === true;
	const bx = cx - basisPos[0],
		by = cy - basisPos[1],
		bz = cz - basisPos[2];

	if (isFat) {
		// Fat path: write into the thin scratch arrays carried in userData, then
		// expand into the duplicated/indexed fat geometry.
		const posArr = line.userData.thinPositions as Float32Array;
		const trailArr = line.userData.thinTrailAlphas as Float32Array;
		const fullArr = line.userData.thinFullAlphas as Float32Array;
		const cap = posArr.length / 3;
		const n = Math.min(validPoints.length, cap);
		for (let k = 0; k < n; k++) {
			posArr[k * 3] = validPoints[k][0] + bx;
			posArr[k * 3 + 1] = validPoints[k][1] + by;
			posArr[k * 3 + 2] = validPoints[k][2] + bz;
		}
		writeOrbitAlphas(
			fullArr.subarray(0, n) as Float32Array,
			trailArr.subarray(0, n) as Float32Array,
			isOpenCurve,
			useTrail
		);
		writeFatOrbitVertices(line.geometry, posArr, trailArr, fullArr, n);
		line.userData.orbitLocalPositions = validPoints;
		return;
	}

	const posAttr = line.geometry.getAttribute('position');
	const trailAttr = line.geometry.getAttribute('trailAlpha');
	const fullAttr = line.geometry.getAttribute('fullAlpha');
	// Clamp to buffer capacity rather than silently skipping — dropping a frame
	// from a too-small buffer would freeze the trail permanently when the SGP4
	// window grows past its construction-time size.
	const cap = posAttr.count;
	const n = Math.min(validPoints.length, cap);

	const posArr = posAttr.array as Float32Array;
	const trailArr = trailAttr.array as Float32Array;
	const fullArr = fullAttr.array as Float32Array;
	for (let k = 0; k < n; k++) {
		posArr[k * 3] = validPoints[k][0] + bx;
		posArr[k * 3 + 1] = validPoints[k][1] + by;
		posArr[k * 3 + 2] = validPoints[k][2] + bz;
	}
	writeOrbitAlphas(
		fullArr.subarray(0, n) as Float32Array,
		trailArr.subarray(0, n) as Float32Array,
		isOpenCurve,
		useTrail
	);
	line.geometry.setDrawRange(0, n);
	// Cache the new orbit-local vertex list for the next focus-basis rebuild.
	line.userData.orbitLocalPositions = validPoints;

	posAttr.needsUpdate = true;
	trailAttr.needsUpdate = true;
	fullAttr.needsUpdate = true;
}

/** Create a radial gradient canvas texture for the star corona glow. */
function makeGlowTexture(color: string, size = 256): CanvasTexture {
	const canvas = document.createElement('canvas');
	canvas.width = size;
	canvas.height = size;
	const ctx = canvas.getContext('2d')!;
	const half = size / 2;
	const gradient = ctx.createRadialGradient(half, half, 0, half, half, half);
	gradient.addColorStop(0, color);
	gradient.addColorStop(0.15, color);
	gradient.addColorStop(0.4, color.replace(')', ', 0.3)').replace('rgb(', 'rgba('));
	gradient.addColorStop(1, 'rgba(0, 0, 0, 0)');
	ctx.fillStyle = gradient;
	ctx.fillRect(0, 0, size, size);
	return new CanvasTexture(canvas);
}

/** Convert hex color like #ffdd44 to rgb() string. */
function hexToRgb(hex: string): string {
	const r = parseInt(hex.slice(1, 3), 16);
	const g = parseInt(hex.slice(3, 5), 16);
	const b = parseInt(hex.slice(5, 7), 16);
	return `rgb(${r}, ${g}, ${b})`;
}

/**
 * Build corona glow sprite + lensflare for a star.
 * The sprite is a soft additive-blended billboard, and the lensflare adds
 * camera-facing flare elements that scale with distance.
 */
export function makeStarGlow(
	radius: number,
	color: string
): { corona: Sprite; lensflare: Lensflare } {
	const rgbColor = color.startsWith('#') ? hexToRgb(color) : color;

	// Corona glow sprite — 6x the star radius for a soft halo
	const glowTexture = makeGlowTexture(rgbColor);
	const coronaMaterial = new SpriteMaterial({
		map: glowTexture,
		blending: AdditiveBlending,
		transparent: true,
		opacity: 0.6,
		depthWrite: false,
		depthTest: true
	});
	const corona = new Sprite(coronaMaterial);
	const glowSize = radius * 6;
	corona.scale.set(glowSize, glowSize, 1);

	// Lensflare — subtle flare elements
	const flareTexture = makeGlowTexture(rgbColor, 128);
	const lensflare = new Lensflare();
	lensflare.addElement(new LensflareElement(flareTexture, 35, 0, new Color(color)));

	return { corona, lensflare };
}

/** Single fixed-size dot for a star, visible when the mesh is sub-pixel. */
export function makeStarPoint(color: string, circleTexture: CanvasTexture): Points {
	const geometry = new BufferGeometry();
	geometry.setAttribute('position', new Float32BufferAttribute(new Float32Array(3), 3));
	const material = new PointsMaterial({
		color,
		map: circleTexture,
		transparent: true,
		size: 6,
		sizeAttenuation: false,
		depthTest: true,
		depthWrite: false
	});
	const points = new Points(geometry, material);
	points.frustumCulled = false;
	return points;
}

const F32_MAX = 3.4028235e38;

export function makePointCloud(
	bodies: PositionedBody[],
	texture: CanvasTexture,
	color: string,
	basisPos: [number, number, number] = [0, 0, 0]
): Points {
	const valid = bodies.filter((b) => {
		const [x, y, z] = b.position;
		if (
			isFinite(x) &&
			Math.abs(x) <= F32_MAX &&
			isFinite(y) &&
			Math.abs(y) <= F32_MAX &&
			isFinite(z) &&
			Math.abs(z) <= F32_MAX
		)
			return true;
		console.warn(
			`Skipping body with non-finite position: id=${b.data.id} name=${b.data.name}`,
			b.position
		);
		return false;
	});
	const positions = new Float32Array(valid.length * 3);
	for (let i = 0; i < valid.length; i++) {
		positions[i * 3] = valid[i].position[0] - basisPos[0];
		positions[i * 3 + 1] = valid[i].position[1] - basisPos[1];
		positions[i * 3 + 2] = valid[i].position[2] - basisPos[2];
	}
	const geometry = new BufferGeometry();
	geometry.setAttribute('position', new Float32BufferAttribute(positions, 3));
	const material = new PointsMaterial({
		map: texture,
		color,
		transparent: true,
		size: 4,
		sizeAttenuation: false,
		depthTest: true,
		depthWrite: false
	});
	const points = new Points(geometry, material);
	points.frustumCulled = false; // visibility managed by context-manager thresholds
	return points;
}

/**
 * Build a Points object whose position attribute is backed by a caller-owned
 * Float32Array. Used by the orbit worker pool, which swaps the backing array
 * each time a worker returns a fresh tick result — so the geometry buffer IS
 * the pool's front buffer, no copy per frame.
 *
 * `drawCount` controls the initial draw range; the caller updates it via
 * geometry.setDrawRange() when a worker returns a different valid count.
 */
export function makePointCloudFromBuffer(
	positions: Float32Array,
	drawCount: number,
	texture: CanvasTexture,
	color: string
): Points {
	const geometry = new BufferGeometry();
	geometry.setAttribute('position', new BufferAttribute(positions, 3));
	geometry.setDrawRange(0, drawCount);
	const material = new PointsMaterial({
		map: texture,
		color,
		transparent: true,
		size: 4,
		sizeAttenuation: false,
		depthTest: true,
		depthWrite: false
	});
	const points = new Points(geometry, material);
	points.frustumCulled = false;
	return points;
}
