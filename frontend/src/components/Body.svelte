<script lang="ts">
	import { T } from '@threlte/core';
	import { BodyType, type HorizonsBody, type SmallBody, type PositionedBody } from '$lib/types';
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
		body: PositionedBody<HorizonsBody> | PositionedBody<SmallBody>;
		onFocus?: (body: PositionedBody<HorizonsBody> | PositionedBody<SmallBody>) => void;
	}

	let { body, onFocus }: Props = $props();

	const isHorizons = 'naifId' in body.data;
	const horizonsData = isHorizons ? (body.data as HorizonsBody) : undefined;

	const name = isHorizons
		? (horizonsData!.name ?? horizonsData!.designation ?? '')
		: ((body.data as SmallBody).name ?? (body.data as SmallBody).fullName);
	const color = PLANET_COLORS[name] ?? DEFAULT_BODY_COLOR;
	const radius = kmToScene(BODY_RADII_KM[name] ?? DEFAULT_BODY_RADIUS_KM);
	const isStar = horizonsData?.type === BodyType.STAR;
	const isSpacecraft = horizonsData?.type === BodyType.SPACECRAFT;
	const majorBody =
		isHorizons &&
		[BodyType.PLANET, BodyType.DWARF_PLANET, BodyType.STAR].includes(horizonsData!.type);
	const drawHalo = majorBody || isSpacecraft;
	const haloVariant: 'major' | 'minor' | 'spacecraft' = majorBody
		? 'major'
		: isSpacecraft
			? 'spacecraft'
			: 'minor';
	const drawTrail = majorBody;
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

	{#if drawHalo}
		<Halo {color} {name} variant={haloVariant} onclick={() => onFocus?.(body)} />
	{/if}
</T.Group>

{#if body.orbitElements && drawTrail}
	<OrbitLine elements={body.orbitElements} {color} center={body.orbitCenter} />
{/if}
