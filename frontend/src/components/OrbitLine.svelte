<script lang="ts">
	import { T } from '@threlte/core';
	import {
		BufferGeometry,
		Color,
		Float32BufferAttribute,
		LineBasicMaterial,
		ShaderMaterial
	} from 'three';
	import type { OrbitalElements } from '$lib/types';
	import { orbitalElementsToEllipse } from '$lib/kepler';

	interface Props {
		elements: OrbitalElements;
		color?: string;
		center?: [number, number, number];
		/** Fraction of the orbit to draw as a trailing arc (0–1). Undefined = full orbit. */
		trailFraction?: number;
	}

	let { elements, color = '#444444', center, trailFraction }: Props = $props();

	const NUM_POINTS = 512;
	const allPoints = orbitalElementsToEllipse(elements, NUM_POINTS);

	function buildFullOrbit() {
		const geometry = new BufferGeometry();
		geometry.setAttribute(
			'position',
			new Float32BufferAttribute(new Float32Array(allPoints.flat()), 3)
		);
		const material = new LineBasicMaterial({ color, transparent: true, opacity: 0.7 });
		return { geometry, material, isLoop: true };
	}

	function buildTrail() {
		// Current mean anomaly (degrees, 0-360)
		const dateJD = Date.now() / 86400000 + 2440587.5;
		const dt = dateJD - elements.epoch;
		const currentMa = (((elements.ma + elements.n * dt) % 360) + 360) % 360;

		// Index in the ellipse array corresponding to current position
		const currentIdx = (currentMa / 360) * NUM_POINTS;
		const trailLen = Math.round(trailFraction! * NUM_POINTS);

		// Extract trail points ending at current position, wrapping around
		const trailPoints: [number, number, number][] = [];
		for (let k = 0; k < trailLen; k++) {
			const idx = Math.round(
				(((currentIdx - trailLen + 1 + k) % NUM_POINTS) + NUM_POINTS) % NUM_POINTS
			);
			trailPoints.push(allPoints[idx]);
		}

		const geometry = new BufferGeometry();
		geometry.setAttribute(
			'position',
			new Float32BufferAttribute(new Float32Array(trailPoints.flat()), 3)
		);

		// Alpha gradient: 0 at tail, 0.6z at head
		const alphas = new Float32Array(trailLen);
		for (let k = 0; k < trailLen; k++) {
			alphas[k] = (k / (trailLen - 1)) * 0.6;
		}
		geometry.setAttribute('alpha', new Float32BufferAttribute(alphas, 1));

		const c = new Color(color);
		const material = new ShaderMaterial({
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

		return { geometry, material, isLoop: false };
	}

	const { geometry, material, isLoop } = trailFraction ? buildTrail() : buildFullOrbit();
</script>

{#if isLoop}
	<T.LineLoop {geometry} {material} position={center ?? [0, 0, 0]} />
{:else}
	<T.Line {geometry} {material} position={center ?? [0, 0, 0]} />
{/if}
