<script lang="ts">
	import { T } from '@threlte/core';
	import { HTML } from '@threlte/extras';
	import type { HorizonsBody, PositionedBody } from '$lib/types';
	import {
		PLANET_COLORS,
		PLANET_RADII,
		DEFAULT_BODY_COLOR,
		DEFAULT_BODY_RADIUS
	} from '$lib/constants';
	import OrbitLine from './OrbitLine.svelte';

	interface Props {
		body: PositionedBody<HorizonsBody>;
		showOrbit?: boolean;
	}

	let { body, showOrbit = true }: Props = $props();

	const color = PLANET_COLORS[body.data.name] ?? DEFAULT_BODY_COLOR;
	const radius = (PLANET_RADII[body.data.name] ?? DEFAULT_BODY_RADIUS) / 10;
	const isMoon = $derived(body.data.parentNaifId !== null);
</script>

<T.Mesh position={body.position}>
	<T.SphereGeometry args={[radius, 16, 16]} />
	<T.MeshStandardMaterial {color} />
	{#if !isMoon}
		<HTML center pointerEvents="none" position.y={radius + 0.05}>
			<span
				class="text-white text-xs whitespace-nowrap select-none"
				style="text-shadow: 0 0 4px black"
			>
				{body.data.name}
			</span>
		</HTML>
	{/if}
</T.Mesh>

{#if showOrbit}
	<OrbitLine elements={body.data} {color} />
{/if}
