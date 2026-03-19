<script lang="ts">
	import { Canvas } from '@threlte/core';
	import { WebGLRenderer } from 'three';
	import SceneContent from './SceneContent.svelte';
	import type { PositionedBody } from '$lib/types';
	import type { MapViewState } from '$lib/url-state';

	interface Props {
		majorBodies: PositionedBody[];
		minorBodies: PositionedBody[];
		initialView: MapViewState;
	}

	let { majorBodies, minorBodies, initialView }: Props = $props();
</script>

<Canvas createRenderer={(canvas) => new WebGLRenderer({ canvas, logarithmicDepthBuffer: true })}>
	<SceneContent {majorBodies} {minorBodies} {initialView} />
</Canvas>
