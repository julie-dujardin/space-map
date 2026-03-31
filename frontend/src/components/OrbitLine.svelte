<script lang="ts">
	import { T } from '@threlte/core';
	import { BufferGeometry, Color, Float32BufferAttribute, ShaderMaterial } from 'three';
	import type { OrbitalElements } from '$lib/types/objects';
	import { orbitalElementsToEllipse } from '$lib/math/kepler';

	interface Props {
		elements: OrbitalElements;
		color?: string;
		center?: [number, number, number];
		/** Fraction of the orbit to draw as a trailing arc (0–1). Undefined = full orbit. */
		trailFraction?: number;
		/** Body's world-space position — used as the trail endpoint so it matches the rendered body. */
		bodyPosition: [number, number, number];
	}

	let { elements, color = '#444444', center, trailFraction, bodyPosition }: Props = $props();

	const NUM_POINTS = 512;
	const ellipse = orbitalElementsToEllipse(elements, NUM_POINTS);

	// Body position in orbit-local coordinates (subtract orbit center)
	const bodyLocal: [number, number, number] = [
		bodyPosition[0] - (center?.[0] ?? 0),
		bodyPosition[1] - (center?.[1] ?? 0),
		bodyPosition[2] - (center?.[2] ?? 0)
	];

	// Find the first ellipse point BEHIND the body (orbit direction = increasing index).
	// Nearest point might be slightly ahead, so check neighbors to pick the one behind.
	function findTrailStart(): number {
		let nearest = 0;
		let best = Infinity;
		for (let j = 0; j < NUM_POINTS; j++) {
			const d =
				(ellipse[j][0] - bodyLocal[0]) ** 2 +
				(ellipse[j][1] - bodyLocal[1]) ** 2 +
				(ellipse[j][2] - bodyLocal[2]) ** 2;
			if (d < best) {
				best = d;
				nearest = j;
			}
		}
		const prev = (nearest - 1 + NUM_POINTS) % NUM_POINTS;
		const next = (nearest + 1) % NUM_POINTS;
		const distPrev =
			(ellipse[prev][0] - bodyLocal[0]) ** 2 +
			(ellipse[prev][1] - bodyLocal[1]) ** 2 +
			(ellipse[prev][2] - bodyLocal[2]) ** 2;
		const distNext =
			(ellipse[next][0] - bodyLocal[0]) ** 2 +
			(ellipse[next][1] - bodyLocal[1]) ** 2 +
			(ellipse[next][2] - bodyLocal[2]) ** 2;
		return distPrev < distNext ? prev : nearest;
	}

	const trailStart = findTrailStart();

	// Build trail points: body position first, then ellipse points walking backwards
	const trailLen = trailFraction ? Math.round(trailFraction * NUM_POINTS) : NUM_POINTS;
	const closeLoop = !trailFraction; // full orbits end back at body to close the gap
	const points: [number, number, number][] = [bodyLocal];
	for (let k = 0; k < trailLen - 1; k++) {
		points.push(ellipse[(((trailStart - k) % NUM_POINTS) + NUM_POINTS) % NUM_POINTS]);
	}
	if (closeLoop) points.push(bodyLocal);

	// Alpha gradient: bright at body, fading along the trail
	const maxAlpha = trailFraction ? 0.6 : 0.9;
	const minAlpha = trailFraction ? 0 : maxAlpha / 3;
	const alphas = new Float32Array(points.length);
	for (let k = 0; k < points.length; k++) {
		alphas[k] = maxAlpha - (k / (points.length - 1)) * (maxAlpha - minAlpha);
	}

	// Geometry
	const geometry = new BufferGeometry();
	geometry.setAttribute('position', new Float32BufferAttribute(new Float32Array(points.flat()), 3));
	geometry.setAttribute('alpha', new Float32BufferAttribute(alphas, 1));

	const material = new ShaderMaterial({
		transparent: true,
		uniforms: { uColor: { value: new Color(color) } },
		vertexShader: `
			attribute float alpha;
			varying float vAlpha;
			void main() {
				vAlpha = alpha;
				gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
			}
		`,
		fragmentShader: `
			uniform vec3 uColor;
			varying float vAlpha;
			void main() {
				gl_FragColor = vec4(uColor, vAlpha);
			}
		`
	});
</script>

<T.Line {geometry} {material} position={center ?? [0, 0, 0]} />
