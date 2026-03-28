<script lang="ts">
	import { T } from '@threlte/core';
	import { BufferGeometry, Color, Float32BufferAttribute, ShaderMaterial } from 'three';
	import type { OrbitalElements } from '$lib/types';
	import { orbitalElementsToEllipse, dateToJD } from '$lib/kepler';

	interface Props {
		elements: OrbitalElements;
		color?: string;
		center?: [number, number, number];
		/** Fraction of the orbit to draw as a trailing arc (0–1). Undefined = full orbit. */
		trailFraction?: number;
		date: Date;
	}

	let { elements, color = '#444444', center, trailFraction, date }: Props = $props();

	const NUM_POINTS = 512;
	const allPoints = orbitalElementsToEllipse(elements, NUM_POINTS);

	// Current mean anomaly (degrees, 0-360)
	const dt = dateToJD(date) - elements.epoch;
	const currentMa = (((elements.ma + elements.n * dt) % 360) + 360) % 360;
	const currentIdx = (currentMa / 360) * NUM_POINTS;

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
			points = [];
			for (let k = 0; k < trailLen; k++) {
				const idx = Math.round(
					(((currentIdx - trailLen + 1 + k) % NUM_POINTS) + NUM_POINTS) % NUM_POINTS
				);
				points.push(allPoints[idx]);
			}
			// Alpha gradient: 0 at tail, 0.6 at head
			alphas = new Float32Array(trailLen);
			for (let k = 0; k < trailLen; k++) {
				alphas[k] = (k / (trailLen - 1)) * 0.6;
			}
		} else {
			// Full orbit reordered: start just ahead of the planet, end at the planet.
			// T.Line doesn't connect last→first, so the gap creates a hard alpha cut.
			const MAX_ALPHA = 0.9;
			const MIN_ALPHA = MAX_ALPHA * (1 / 3);
			const startIdx = Math.ceil(currentIdx) % NUM_POINTS;
			points = [];
			for (let k = 0; k <= NUM_POINTS; k++) {
				points.push(allPoints[(startIdx + k) % NUM_POINTS]);
			}
			// Linear gradient: MIN at start (just ahead of planet) → MAX at end (planet)
			alphas = new Float32Array(NUM_POINTS + 1);
			for (let k = 0; k <= NUM_POINTS; k++) {
				alphas[k] = MIN_ALPHA + (k / NUM_POINTS) * (MAX_ALPHA - MIN_ALPHA);
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
