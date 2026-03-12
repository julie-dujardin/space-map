<script lang="ts">
	import { Canvas } from '@threlte/core';
	import { WebGLRenderer } from 'three';
	import SceneContent from './SceneContent.svelte';
	import type { HorizonsBody, SmallBody, Satellite, PositionedBody } from '$lib/types';
	import type { MapViewState } from '$lib/url-state';

	interface Props {
		bodies: PositionedBody<HorizonsBody>[];
		smallBodies: PositionedBody<SmallBody>[];
		satellites: Satellite[];
		earthPosition: [number, number, number];
		initialView: MapViewState;
	}

	let { bodies, smallBodies, satellites, earthPosition, initialView }: Props = $props();
</script>

<Canvas createRenderer={(canvas) => new WebGLRenderer({ canvas, logarithmicDepthBuffer: true })}>
	<SceneContent {bodies} {smallBodies} {satellites} {earthPosition} {initialView} />
</Canvas>
