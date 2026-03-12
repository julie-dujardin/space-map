<script lang="ts">
	import { T } from '@threlte/core';
	import { BufferGeometry, Float32BufferAttribute, LineBasicMaterial } from 'three';
	import type { OrbitalElements } from '$lib/types';
	import { orbitalElementsToEllipse } from '$lib/kepler';

	interface Props {
		elements: OrbitalElements;
		color?: string;
		center?: [number, number, number];
	}

	let { elements, color = '#444444', center }: Props = $props();

	const points = orbitalElementsToEllipse(elements);
	const geometry = new BufferGeometry();
	const vertices = new Float32Array(points.flat());
	geometry.setAttribute('position', new Float32BufferAttribute(vertices, 3));
	const material = new LineBasicMaterial({ color, transparent: true, opacity: 0.4 });
</script>

<T.LineLoop {geometry} {material} position={center ?? [0, 0, 0]} />
