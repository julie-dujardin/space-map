<script lang="ts">
	import { T } from '@threlte/core';
	import { HTML } from '@threlte/extras';
	import { BodyType, type HorizonsBody, type PositionedBody } from '$lib/types';
	import {
		PLANET_COLORS,
		BODY_RADII_KM,
		DEFAULT_BODY_COLOR,
		DEFAULT_BODY_RADIUS_KM,
		kmToScene
	} from '$lib/constants';
	import OrbitLine from './OrbitLine.svelte';
	import Halo from './Halo.svelte';

	interface Props {
		body: PositionedBody<HorizonsBody>;
		onFocus?: (body: PositionedBody<HorizonsBody>) => void;
	}

	let { body, onFocus }: Props = $props();

	const name = body.data.name ?? body.data.designation ?? '';
	const color = PLANET_COLORS[name] ?? DEFAULT_BODY_COLOR;
	const radius = kmToScene(BODY_RADII_KM[name] ?? DEFAULT_BODY_RADIUS_KM);
	const isStar = body.data.type === BodyType.STAR;
</script>

<T.Group position={body.position}>
	{#if isStar}
		<T.PointLight intensity={2} />
	{/if}

	<T.Mesh onclick={() => onFocus?.(body)}>
		<T.SphereGeometry args={[radius, isStar ? 32 : 16, isStar ? 32 : 16]} />
		{#if isStar}
			<T.MeshBasicMaterial {color} />
		{:else}
			<T.MeshStandardMaterial {color} />
		{/if}
	</T.Mesh>

	{#if [BodyType.PLANET, BodyType.DWARF_PLANET, BodyType.STAR].includes(body.data.type)}
		<Halo {color} onclick={() => onFocus?.(body)} />
	{/if}

	{#if [BodyType.PLANET, BodyType.DWARF_PLANET, BodyType.STAR].includes(body.data.type)}
		<HTML center pointerEvents="none" position.y={0}>
			<span
				class="text-white text-xs whitespace-nowrap select-none"
				style="text-shadow: 0 0 4px black"
			>
				{body.data.name ?? body.data.designation}
			</span>
		</HTML>
	{/if}
</T.Group>

{#if body.orbitElements && [BodyType.PLANET, BodyType.DWARF_PLANET, BodyType.STAR].includes(body.data.type)}
	<OrbitLine elements={body.orbitElements} {color} />
{/if}
