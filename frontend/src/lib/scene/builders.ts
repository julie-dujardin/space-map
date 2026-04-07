import {
	BufferGeometry,
	CanvasTexture,
	Color,
	Float32BufferAttribute,
	Line,
	Points,
	PointsMaterial,
	ShaderMaterial,
	Vector3
} from 'three';
import { orbitalElementsToCurve } from '$lib/math/kepler';
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
	const trailFraction = useTrail ? (isOpenCurve ? 3 / 3 : 1 / 3) : undefined;
	const trailLen = trailFraction ? Math.round(trailFraction * NUM_ORBIT_POINTS) : NUM_ORBIT_POINTS;
	const closeLoop = !trailFraction;

	const points: [number, number, number][] = [bodyLocal];
	for (let k = 0; k < trailLen - 1; k++) {
		if (isOpenCurve) {
			// Open curve: clamp to bounds instead of wrapping
			const idx = Math.max(trailStart - k, 0);
			points.push(curve[idx]);
			if (idx === 0) break; // reached start of curve
		} else {
			points.push(
				curve[(((trailStart - k) % NUM_ORBIT_POINTS) + NUM_ORBIT_POINTS) % NUM_ORBIT_POINTS]
			);
		}
	}
	if (closeLoop) points.push(bodyLocal);

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

	const alphas = new Float32Array(validPoints.length);
	{
		const maxAlpha = closeLoop ? 0.9 : 0.6;
		const minAlpha = closeLoop ? maxAlpha / 3 : 0;
		for (let k = 0; k < validPoints.length; k++) {
			alphas[k] = maxAlpha - (k / (validPoints.length - 1)) * (maxAlpha - minAlpha);
		}
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
	geometry.setAttribute('alpha', new Float32BufferAttribute(alphas, 1));

	const material = new ShaderMaterial({
		transparent: true,
		uniforms: {
			uColor: { value: new Color(color) },
			uCenterOffset: { value: new Vector3() },
			uAlphaMultiplier: { value: 1.0 }
		},
		vertexShader: `
			uniform vec3 uCenterOffset;
			attribute float alpha;
			varying float vAlpha;
			void main() {
				vAlpha = alpha;
				vec3 relPos = position + uCenterOffset;
				gl_Position = projectionMatrix * vec4(mat3(viewMatrix) * relPos, 1.0);
			}
		`,
		fragmentShader: `
			uniform vec3 uColor;
			uniform float uAlphaMultiplier;
			varying float vAlpha;
			void main() {
				gl_FragColor = vec4(uColor, clamp(vAlpha * uAlphaMultiplier, 0.0, 1.0));
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
	return new Points(geometry, material);
}
