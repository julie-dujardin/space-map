<script lang="ts">
	import { T } from '@threlte/core';
	import { BufferGeometry, Float32BufferAttribute, PointsMaterial } from 'three';
	import type { SmallBody, PositionedBody } from '$lib/types';

	interface Props {
		bodies: PositionedBody<SmallBody>[];
	}

	let { bodies }: Props = $props();

	const geometry = new BufferGeometry();
	const positions = new Float32Array(bodies.flatMap((b) => b.position));
	geometry.setAttribute('position', new Float32BufferAttribute(positions, 3));

	const material = new PointsMaterial({ color: '#88aacc', size: 0.15, sizeAttenuation: true });
</script>

<T.Points {geometry} {material} />
