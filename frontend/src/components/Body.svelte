<script lang="ts">
	import { T } from '@threlte/core';
	import { ObjectType } from '$lib/types/objects';
	import type { PositionedBody } from '$lib/types/objects';
	import {
		BODY_COLORS,
		BODY_RADII_KM,
		DEFAULT_BODY_COLOR,
		DEFAULT_BODY_RADIUS_KM
	} from '$lib/constants';
	import { kmToScene } from '$lib/math/units';
	import OrbitLine from './OrbitLine.svelte';
	import Halo from './Halo.svelte';

	interface Props {
		body: PositionedBody;
		onFocus?: (body: PositionedBody) => void;
	}

	let { body, onFocus }: Props = $props();

	const id = body.data.id;
	const name = body.data.name ?? '';
	const objType = body.data.objectType;
	const color = BODY_COLORS[id] ?? DEFAULT_BODY_COLOR;
	const rawRadiusKm =
		BODY_RADII_KM[id] ??
		(Number.isFinite(body.data.radiusKm) ? body.data.radiusKm : DEFAULT_BODY_RADIUS_KM);
	const radius = kmToScene(rawRadiusKm);
	const isStar = objType === ObjectType.STAR;
	const majorBody =
		objType === ObjectType.PLANET ||
		objType === ObjectType.DWARF_PLANET ||
		objType === ObjectType.STAR ||
		(objType === ObjectType.MOON && !/^\d+$/.test(name[0]));
	const drawHalo = majorBody;
	const haloVariant: 'major' | 'minor' | 'spacecraft' = majorBody
		? 'major'
		: objType === ObjectType.SPACECRAFT
			? 'spacecraft'
			: 'minor';
	const drawTrail = majorBody && !isStar;
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
	<OrbitLine
		elements={body.orbitElements}
		{color}
		bodyPosition={body.position}
		center={body.orbitCenter}
		trailFraction={objType === ObjectType.DWARF_PLANET || objType === ObjectType.MOON
			? 1 / 3
			: undefined}
	/>
{/if}
