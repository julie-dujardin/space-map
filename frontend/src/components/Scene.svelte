<script lang="ts">
	import { Canvas } from '@threlte/core';
	import { WebGLRenderer } from 'three';
	import SceneContent from './SceneContent.svelte';
	import type { PositionedBody } from '$lib/types/objects';
	import type { MapViewState } from '$lib/url-state';

	interface Props {
		initialView: MapViewState;
		onFocusChange?: (body: PositionedBody | undefined) => void;
	}

	let { initialView, onFocusChange }: Props = $props();
</script>

<Canvas createRenderer={(canvas) => new WebGLRenderer({ canvas, logarithmicDepthBuffer: true })}>
	<SceneContent {initialView} {onFocusChange} />
</Canvas>
