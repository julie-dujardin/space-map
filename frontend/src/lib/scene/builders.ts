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
import { orbitalElementsToEllipse } from '$lib/math/kepler';
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

export function makeOrbitLine(body: PositionedBody, color: string): Line {
	const { orbitElements, orbitCenter, data } = body;
	if (!orbitElements) throw new Error('makeOrbitLine called without orbitElements');

	const ellipse = orbitalElementsToEllipse(orbitElements, NUM_ORBIT_POINTS);

	// Body position in orbit-local coordinates
	const cx = orbitCenter?.[0] ?? 0;
	const cy = orbitCenter?.[1] ?? 0;
	const cz = orbitCenter?.[2] ?? 0;
	const bodyLocal: [number, number, number] = [
		body.position[0] - cx,
		body.position[1] - cy,
		body.position[2] - cz
	];

	// Find trail start point (behind the body in orbital direction)
	let nearest = 0;
	let best = Infinity;
	for (let j = 0; j < NUM_ORBIT_POINTS; j++) {
		const d =
			(ellipse[j][0] - bodyLocal[0]) ** 2 +
			(ellipse[j][1] - bodyLocal[1]) ** 2 +
			(ellipse[j][2] - bodyLocal[2]) ** 2;
		if (d < best) {
			best = d;
			nearest = j;
		}
	}
	const prev = (nearest - 1 + NUM_ORBIT_POINTS) % NUM_ORBIT_POINTS;
	const next = (nearest + 1) % NUM_ORBIT_POINTS;
	const distPrev =
		(ellipse[prev][0] - bodyLocal[0]) ** 2 +
		(ellipse[prev][1] - bodyLocal[1]) ** 2 +
		(ellipse[prev][2] - bodyLocal[2]) ** 2;
	const distNext =
		(ellipse[next][0] - bodyLocal[0]) ** 2 +
		(ellipse[next][1] - bodyLocal[1]) ** 2 +
		(ellipse[next][2] - bodyLocal[2]) ** 2;
	const trailStart = distPrev < distNext ? prev : nearest;

	const useTrail =
		data.objectType === ObjectType.DWARF_PLANET ||
		data.objectType === ObjectType.MOON ||
		isAsteroid(data.objectType);
	const trailFraction = useTrail ? 1 / 3 : undefined;
	const trailLen = trailFraction ? Math.round(trailFraction * NUM_ORBIT_POINTS) : NUM_ORBIT_POINTS;
	const closeLoop = !trailFraction;

	const points: [number, number, number][] = [bodyLocal];
	for (let k = 0; k < trailLen - 1; k++) {
		points.push(
			ellipse[(((trailStart - k) % NUM_ORBIT_POINTS) + NUM_ORBIT_POINTS) % NUM_ORBIT_POINTS]
		);
	}
	if (closeLoop) points.push(bodyLocal);

	const maxAlpha = trailFraction ? 0.6 : 0.9;
	const minAlpha = trailFraction ? 0 : maxAlpha / 3;
	const alphas = new Float32Array(points.length);
	for (let k = 0; k < points.length; k++) {
		alphas[k] = maxAlpha - (k / (points.length - 1)) * (maxAlpha - minAlpha);
	}

	const geometry = new BufferGeometry();
	geometry.setAttribute('position', new Float32BufferAttribute(new Float32Array(points.flat()), 3));
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
	line.frustumCulled = false; // geometry is orbit-local; shader repositions it via uCenterOffset
	line.userData.orbitCenter = new Vector3(cx, cy, cz);
	return line;
}

export function makePointCloud(bodies: PositionedBody[], texture: CanvasTexture): Points {
	const positions = new Float32Array(bodies.length * 3);
	for (let i = 0; i < bodies.length; i++) {
		positions[i * 3] = bodies[i].position[0];
		positions[i * 3 + 1] = bodies[i].position[1];
		positions[i * 3 + 2] = bodies[i].position[2];
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
