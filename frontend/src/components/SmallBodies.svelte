<script lang="ts">
	import { T } from '@threlte/core';
	import { BufferGeometry, CanvasTexture, Float32BufferAttribute, PointsMaterial } from 'three';
	import type { PositionedBody } from '$lib/types/objects';

	interface Props {
		bodies: PositionedBody[];
	}

	let { bodies }: Props = $props();

	const geometry = new BufferGeometry();
	const positions = new Float32Array(bodies.flatMap((b) => b.position));
	geometry.setAttribute('position', new Float32BufferAttribute(positions, 3));

	// Shared circle texture for all minor halos
	const texSize = 32;
	const canvas = document.createElement('canvas');
	canvas.width = texSize;
	canvas.height = texSize;
	const ctx = canvas.getContext('2d')!;
	ctx.beginPath();
	ctx.arc(texSize / 2, texSize / 2, texSize / 2 - 2, 0, Math.PI * 2);
	ctx.fillStyle = '#aaaaaa';
	ctx.globalAlpha = 0.3;
	ctx.fill();
	const circleTexture = new CanvasTexture(canvas);

	const material = new PointsMaterial({
		map: circleTexture,
		transparent: true,
		size: 4,
		sizeAttenuation: false,
		depthTest: false
	});
</script>

<T.Points {geometry} {material} />
