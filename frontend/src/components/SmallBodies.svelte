<script lang="ts">
	import { T, useTask } from '@threlte/core';
	import { getContext, untrack } from 'svelte';
	import {
		BufferGeometry,
		CanvasTexture,
		Float32BufferAttribute,
		Points,
		PointsMaterial
	} from 'three';
	import type { PositionedBody } from '$lib/types/objects';
	import type { ContextManager } from '$lib/context-manager.svelte';

	interface Props {
		bodies: PositionedBody[];
		groupParentId?: number; // present only for spacecraft groups; absent = always visible
	}

	let { bodies, groupParentId }: Props = $props();

	const ctx = getContext<ContextManager>('ctx');

	const geometry = new BufferGeometry();
	const positions = new Float32Array(untrack(() => bodies.flatMap((b) => b.position)));
	geometry.setAttribute('position', new Float32BufferAttribute(positions, 3));

	// Shared circle texture for all minor halos
	const texSize = 32;
	const canvas = document.createElement('canvas');
	canvas.width = texSize;
	canvas.height = texSize;
	const c = canvas.getContext('2d')!;
	c.beginPath();
	c.arc(texSize / 2, texSize / 2, texSize / 2 - 2, 0, Math.PI * 2);
	c.fillStyle = '#aaaaaa';
	c.globalAlpha = 0.3;
	c.fill();
	const circleTexture = new CanvasTexture(canvas);

	const material = new PointsMaterial({
		map: circleTexture,
		transparent: true,
		size: 4,
		sizeAttenuation: false,
		depthTest: false
	});

	let pointsRef = $state<Points | undefined>();

	useTask(() => {
		if (pointsRef && groupParentId !== undefined) {
			pointsRef.visible = ctx.isSpacecraftGroupVisible(groupParentId);
		}
	});
</script>

<T.Points {geometry} {material} bind:ref={pointsRef} />
