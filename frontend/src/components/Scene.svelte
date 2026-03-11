<script lang="ts">
	import { Canvas } from '@threlte/core';
	import { WebGLRenderer } from 'three';
	import SceneContent from './SceneContent.svelte';
	import type { HorizonsBody, SmallBody, Satellite, PositionedBody } from '$lib/types';

	interface Props {
		bodies: PositionedBody<HorizonsBody>[];
		smallBodies: PositionedBody<SmallBody>[];
		satellites: Satellite[];
		earthPosition: [number, number, number];
	}

	let { bodies, smallBodies, satellites, earthPosition }: Props = $props();
</script>

<Canvas createRenderer={(canvas) => new WebGLRenderer({ canvas, logarithmicDepthBuffer: true })}>
	<SceneContent {bodies} {smallBodies} {satellites} {earthPosition} />
</Canvas>
