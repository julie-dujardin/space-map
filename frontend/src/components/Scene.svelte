<script lang="ts">
	import { T, Canvas } from '@threlte/core';
	import { OrbitControls } from '@threlte/extras';
	import Sun from './Sun.svelte';
	import Planet from './Planet.svelte';
	import SmallBodies from './SmallBodies.svelte';
	import Satellites from './Satellites.svelte';
	import type { HorizonsBody, SmallBody, Satellite, PositionedBody } from '$lib/types';

	interface Props {
		bodies: PositionedBody<HorizonsBody>[];
		smallBodies: PositionedBody<SmallBody>[];
		satellites: Satellite[];
		earthPosition: [number, number, number];
	}

	let { bodies, smallBodies, satellites, earthPosition }: Props = $props();
</script>

<Canvas>
	<T.PerspectiveCamera makeDefault position={[0, 30, 30]} fov={60}>
		<OrbitControls enableDamping />
	</T.PerspectiveCamera>

	<T.AmbientLight intensity={0.4} />

	<Sun />

	{#each bodies as body (body.data.naifId)}
		<Planet {body} showOrbit={body.data.parentNaifId === null} />
	{/each}

	<SmallBodies bodies={smallBodies} />
	<Satellites {satellites} {earthPosition} />
</Canvas>
