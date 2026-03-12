<script lang="ts">
	import { T, useTask } from '@threlte/core';
	import { OrbitControls, interactivity } from '@threlte/extras';
	import { Vector3 } from 'three';
	import type { OrbitControls as OrbitControlsType } from 'three/addons/controls/OrbitControls.js';
	import Body from './Body.svelte';
	import {
		type HorizonsBody,
		type SmallBody,
		type Satellite,
		type PositionedBody
	} from '$lib/types';
	import SmallBodies from './SmallBodies.svelte';

	interface Props {
		bodies: PositionedBody<HorizonsBody>[];
		smallBodies: PositionedBody<SmallBody>[];
		satellites: Satellite[];
		earthPosition: [number, number, number];
	}

	let { bodies, smallBodies }: Props = $props();

	interactivity();

	let controlsRef = $state<OrbitControlsType>();

	const sunBody = bodies.find((b) => b.data.naifId === 10);
	let focusTarget = $state<[number, number, number]>(sunBody?.position ?? [0, 0, 0]);

	const targetVec = new Vector3();

	useTask(() => {
		if (!controlsRef) return;
		targetVec.set(...focusTarget);
		if (controlsRef.target.distanceToSquared(targetVec) > 0.0001) {
			controlsRef.target.lerp(targetVec, 0.08);
		} else {
			controlsRef.target.copy(targetVec);
		}
		controlsRef.update();
	});

	function handleFocus(body: PositionedBody<HorizonsBody | SmallBody>) {
		focusTarget = body.position;
	}
</script>

<T.PerspectiveCamera makeDefault position={[0, 30, 30]} fov={60} near={0.0001} far={100000}>
	<OrbitControls bind:ref={controlsRef} enableDamping />
</T.PerspectiveCamera>

<T.AmbientLight intensity={0.4} />

{#each bodies as body (body.data.naifId)}
	<Body {body} onFocus={handleFocus} />
{/each}

{#if smallBodies.length > 0}
	<SmallBodies bodies={smallBodies} />
{/if}
