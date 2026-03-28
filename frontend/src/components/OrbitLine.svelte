<script lang="ts">
	import { T } from '@threlte/core';
	import { BufferGeometry, Color, Float32BufferAttribute, ShaderMaterial } from 'three';
	import type { OrbitalElements } from '$lib/types';
	import { orbitalElementsToEllipse } from '$lib/kepler';

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
	const allPoints = orbitalElementsToEllipse(elements, NUM_POINTS);

	// Body position in orbit-local coordinates (subtract orbit center)
	const cx = center?.[0] ?? 0;
	const cy = center?.[1] ?? 0;
	const cz = center?.[2] ?? 0;
	const bodyLocal: [number, number, number] = [
		bodyPosition[0] - cx,
		bodyPosition[1] - cy,
		bodyPosition[2] - cz
	];

	// Find the first ellipse point BEHIND the body (in orbit direction = increasing index)
	let nearestIdx = 0;
	let bestDist = Infinity;
	for (let j = 0; j < NUM_POINTS; j++) {
		const dx = allPoints[j][0] - bodyLocal[0];
		const dy = allPoints[j][1] - bodyLocal[1];
		const dz = allPoints[j][2] - bodyLocal[2];
		const d = dx * dx + dy * dy + dz * dz;
		if (d < bestDist) {
			bestDist = d;
			nearestIdx = j;
		}
	}
	// If the previous neighbor is closer than the next, the body is between prev and nearest,
	// meaning nearest is ahead → step back so we start behind the body.
	const prevIdx = (nearestIdx - 1 + NUM_POINTS) % NUM_POINTS;
	const nextIdx = (nearestIdx + 1) % NUM_POINTS;
	const distPrev =
		(allPoints[prevIdx][0] - bodyLocal[0]) ** 2 +
		(allPoints[prevIdx][1] - bodyLocal[1]) ** 2 +
		(allPoints[prevIdx][2] - bodyLocal[2]) ** 2;
	const distNext =
		(allPoints[nextIdx][0] - bodyLocal[0]) ** 2 +
		(allPoints[nextIdx][1] - bodyLocal[1]) ** 2 +
		(allPoints[nextIdx][2] - bodyLocal[2]) ** 2;
	const currentIdx = distPrev < distNext ? prevIdx : nearestIdx;

	function buildAlphaShader() {
		const c = new Color(color);
		return new ShaderMaterial({
			transparent: true,
			uniforms: { uColor: { value: c } },
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
	}

	function buildOrbit() {
		// For partial trails, extract a subset; for full orbits, use all points
		let points: [number, number, number][];
		let alphas: Float32Array;

		if (trailFraction) {
			const trailLen = Math.round(trailFraction * NUM_POINTS);
			// Start at body, walk backwards along orbit
			points = [bodyLocal];
			for (let k = 0; k < trailLen - 1; k++) {
				const idx = (((currentIdx - k) % NUM_POINTS) + NUM_POINTS) % NUM_POINTS;
				points.push(allPoints[idx]);
			}
			// Alpha gradient: 0.6 at body (head), 0 at tail
			alphas = new Float32Array(trailLen);
			for (let k = 0; k < trailLen; k++) {
				alphas[k] = 0.6 * (1 - k / (trailLen - 1));
			}
		} else {
			// Full orbit: start at body, walk backwards around the full orbit.
			// T.Line doesn't connect last→first, so the gap creates a hard alpha cut.
			const MAX_ALPHA = 0.9;
			const MIN_ALPHA = MAX_ALPHA * (1 / 3);
			points = [bodyLocal];
			for (let k = 0; k < NUM_POINTS; k++) {
				const idx = (((currentIdx - k) % NUM_POINTS) + NUM_POINTS) % NUM_POINTS;
				points.push(allPoints[idx]);
			}
			// Close the gap: end at bodyLocal again with MIN_ALPHA
			points.push(bodyLocal);
			// Alpha gradient: MAX at body (head) → MIN at tail → MIN at body again
			const totalPts = NUM_POINTS + 2;
			alphas = new Float32Array(totalPts);
			for (let k = 0; k < totalPts; k++) {
				alphas[k] = MAX_ALPHA - (k / (totalPts - 1)) * (MAX_ALPHA - MIN_ALPHA);
			}
		}

		const geometry = new BufferGeometry();
		geometry.setAttribute(
			'position',
			new Float32BufferAttribute(new Float32Array(points.flat()), 3)
		);
		geometry.setAttribute('alpha', new Float32BufferAttribute(alphas, 1));

		return { geometry, material: buildAlphaShader() };
	}

	const { geometry, material } = buildOrbit();
</script>

<T.Line {geometry} {material} position={center ?? [0, 0, 0]} />
