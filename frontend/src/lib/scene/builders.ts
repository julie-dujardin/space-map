import {
	AdditiveBlending,
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
import { orbitalElementsToCurve } from '$lib/math/orbit/curves';
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

export function makeOrbitLine(
	body: PositionedBody,
	color: string,
	basisPos: [number, number, number] = [0, 0, 0]
): Line {
	const { orbitElements, orbitCenter, data } = body;
	if (!orbitElements) throw new Error('makeOrbitLine called without orbitElements');

	const { points: curve, isOpen: isOpenCurve } = orbitalElementsToCurve(
		orbitElements,
		NUM_ORBIT_POINTS
	);

	// Body position in orbit-local coordinates
	const cx = orbitCenter?.[0] ?? 0;
	const cy = orbitCenter?.[1] ?? 0;
	const cz = orbitCenter?.[2] ?? 0;
	const bodyLocal: [number, number, number] = [
		body.position[0] - cx,
		body.position[1] - cy,
		body.position[2] - cz
	];

	// Find nearest curve point to the body
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

	// Determine trail direction (the "behind" neighbor is the trail start)
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

	const useTrail =
		isOpenCurve ||
		data.objectType === ObjectType.DWARF_PLANET ||
		data.objectType === ObjectType.MOON ||
		isAsteroid(data.objectType);

	// Always build the full orbit so we can show it when focused
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

	// Filter out any points with NaN/Infinity coordinates (degenerate orbital elements)
	const validPoints = points.filter((p) => p.every(Number.isFinite));
	if (validPoints.length < 2) {
		const geometry = new BufferGeometry();
		geometry.setAttribute('position', new Float32BufferAttribute(new Float32Array(6), 3));
		const material = new ShaderMaterial({ transparent: true });
		const line = new Line(geometry, material);
		line.visible = false;
		return line;
	}

	// Full-orbit alphas: shown when focused (or always for planets)
	const fullAlphas = new Float32Array(validPoints.length);
	{
		const maxAlpha = 0.9;
		const minAlpha = isOpenCurve ? 0 : maxAlpha / 3;
		for (let k = 0; k < validPoints.length; k++) {
			fullAlphas[k] = maxAlpha - (k / (validPoints.length - 1)) * (maxAlpha - minAlpha);
		}
	}

	// Trail alphas: partial trail when unfocused; same as full for non-trail bodies
	const trailAlphas = new Float32Array(validPoints.length);
	if (useTrail && !isOpenCurve) {
		const trailLen = Math.round(NUM_ORBIT_POINTS / 3);
		const maxAlpha = 0.6;
		for (let k = 0; k < trailLen; k++) {
			trailAlphas[k] = maxAlpha - (k / (trailLen - 1)) * maxAlpha;
		}
	} else {
		trailAlphas.set(fullAlphas);
	}

	// Write positions as focus-relative: orbitLocal + orbitCenter - basisPos (Float64 math, small result)
	const bx = cx - basisPos[0],
		by = cy - basisPos[1],
		bz = cz - basisPos[2];
	const posArr = new Float32Array(validPoints.length * 3);
	for (let k = 0; k < validPoints.length; k++) {
		posArr[k * 3] = validPoints[k][0] + bx;
		posArr[k * 3 + 1] = validPoints[k][1] + by;
		posArr[k * 3 + 2] = validPoints[k][2] + bz;
	}

	const geometry = new BufferGeometry();
	geometry.setAttribute('position', new Float32BufferAttribute(posArr, 3));
	geometry.setAttribute('trailAlpha', new Float32BufferAttribute(trailAlphas, 1));
	geometry.setAttribute('fullAlpha', new Float32BufferAttribute(fullAlphas, 1));

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
	// Store Float64 orbit-local positions for rebuilding when focus changes
	line.userData.orbitCenter = new Vector3(cx, cy, cz);
	line.userData.orbitLocalPositions = validPoints;
	return line;
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

/** Build a corona glow sprite for a star. */
export function makeStarGlow(radius: number, color: string): Sprite {
	const rgbColor = color.startsWith('#') ? hexToRgb(color) : color;

	const glowTexture = makeGlowTexture(rgbColor);
	const coronaMaterial = new SpriteMaterial({
		map: glowTexture,
		blending: AdditiveBlending,
		transparent: true,
		opacity: 0.6,
		depthWrite: false,
		depthTest: false
	});
	const corona = new Sprite(coronaMaterial);
	const glowSize = radius * 6;
	corona.scale.set(glowSize, glowSize, 1);

	return corona;
}

const F32_MAX = 3.4028235e38;

export function makePointCloud(
	bodies: PositionedBody[],
	texture: CanvasTexture,
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
