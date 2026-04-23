import {
	AdditiveBlending,
	BufferAttribute,
	BufferGeometry,
	CanvasTexture,
	Color,
	Float32BufferAttribute,
	Line,
	Points,
	PointsMaterial,
	ShaderMaterial,
	Sprite,
	SpriteMaterial,
	Vector3
} from 'three';
import { Lensflare, LensflareElement } from 'three/addons/objects/Lensflare.js';
import { orbitalElementsToCurve, sgp4Curve } from '$lib/math/orbit/curves';
import { dateToJD } from '$lib/format/date';
import { ObjectType, isAsteroid, type PositionedBody } from '$lib/types/objects';

export const NUM_ORBIT_POINTS = 512;

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

export function makeOrbitLine(
	body: PositionedBody,
	color: string,
	basisPos: [number, number, number] = [0, 0, 0],
	jd: number = dateToJD(new Date())
): Line {
	const { orbitElements, orbitCenter, data } = body;

	// SGP4-backed Earth sats: sample the propagator across the *past* orbital
	// period so the trail ends at the body's current position. data.n is in
	// deg/day for SGP4 bodies (converted in chunk.ts); back-convert to rev/day.
	// Chebyshev-backed bodies ship their curve pre-sampled as an open arc.
	let curve: [number, number, number][];
	let isOpenCurve: boolean;
	if (data.satrec) {
		curve = sgp4Curve(data.satrec, jd, data.n / 360, NUM_ORBIT_POINTS);
		isOpenCurve = true;
	} else if (body.orbitCurve) {
		curve = body.orbitCurve;
		isOpenCurve = true;
	} else {
		if (!orbitElements) throw new Error('makeOrbitLine called without orbitElements');
		const result = orbitalElementsToCurve(orbitElements, NUM_ORBIT_POINTS);
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
	if (validPoints.length < 2) {
		const geometry = new BufferGeometry();
		geometry.setAttribute('position', new Float32BufferAttribute(new Float32Array(6), 3));
		const material = new ShaderMaterial({ transparent: true });
		const line = new Line(geometry, material);
		line.visible = false;
		return line;
	}

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

	const geometry = new BufferGeometry();
	geometry.setAttribute('position', new Float32BufferAttribute(posArr, 3));
	geometry.setAttribute('trailAlpha', new Float32BufferAttribute(trailAlphas, 1));
	geometry.setAttribute('fullAlpha', new Float32BufferAttribute(fullAlphas, 1));
	geometry.setDrawRange(0, validPoints.length);

	const material = new ShaderMaterial({
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

	const line = new Line(geometry, material);
	line.frustumCulled = false; // shader repositions geometry via uCenterOffset
	line.visible = false; // updateBodyVisibility sets the correct state next frame; avoids a 1-frame flash when added mid-load
	// Store Float64 orbit-local positions for rebuilding when focus changes,
	// and the static curve + flags for per-frame trail refresh while time plays.
	line.userData.orbitCenter = new Vector3(cx, cy, cz);
	line.userData.orbitLocalPositions = validPoints;
	line.userData.orbitCurve = curve;
	line.userData.isOpenCurve = isOpenCurve;
	line.userData.useTrail = useTrail;
	return line;
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
export function refreshOrbitLineGeometry(
	body: PositionedBody,
	line: Line,
	basisPos: [number, number, number],
	jd: number
): void {
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
	}

	const validPoints = buildOrbitTrailPoints(body, curve, isOpenCurve, cx, cy, cz);
	if (validPoints.length < 2) return;

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
	const bx = cx - basisPos[0],
		by = cy - basisPos[1],
		bz = cz - basisPos[2];
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
