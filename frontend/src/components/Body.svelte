<script lang="ts">
	import { T, useTask } from '@threlte/core';
	import { getContext } from 'svelte';
	import { Group } from 'three';
	import { ObjectType, isMajorBody, type PositionedBody } from '$lib/types/objects';
	import {
		BODY_COLORS,
		BODY_RADII_KM,
		DEFAULT_BODY_COLOR,
		DEFAULT_BODY_RADIUS_KM
	} from '$lib/constants';
	import { kmToScene } from '$lib/math/units';
	import OrbitLine from './OrbitLine.svelte';
	import Halo from './Halo.svelte';
	import type { ContextManager } from '$lib/context-manager.svelte';

	interface Props {
		body: PositionedBody;
		onFocus?: (body: PositionedBody) => void;
	}

	let { body, onFocus }: Props = $props();

	const ctx = getContext<ContextManager>('ctx');

	const id = body.data.id;
	const name = body.data.name ?? '';
	const objType = body.data.objectType;
	const color = BODY_COLORS[id] ?? DEFAULT_BODY_COLOR;
	const rawRadiusKm =
		BODY_RADII_KM[id] ??
		(Number.isFinite(body.data.radiusKm) ? body.data.radiusKm : DEFAULT_BODY_RADIUS_KM);
	const radius = kmToScene(rawRadiusKm);
	const isStar = objType === ObjectType.STAR;
	const haloVariant: 'major' | 'minor' | 'spacecraft' = isMajorBody(objType)
		? 'major'
		: objType === ObjectType.SPACECRAFT
			? 'spacecraft'
			: 'minor';

	let bodyGroupRef = $state<Group | undefined>();
	let haloWrapRef = $state<Group | undefined>();
	let orbitWrapRef = $state<Group | undefined>();

	useTask(() => {
		const bodyVisible = ctx.isMajorBodyVisible(body);
		const full = ctx.hasFullRendering(body);
		if (bodyGroupRef) bodyGroupRef.visible = bodyVisible;
		if (haloWrapRef) haloWrapRef.visible = full;
		if (orbitWrapRef) orbitWrapRef.visible = full;
	});
</script>

<T.Group position={body.position} bind:ref={bodyGroupRef}>
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

	<T.Group bind:ref={haloWrapRef}>
		<Halo {color} {name} variant={haloVariant} onclick={() => onFocus?.(body)} />
	</T.Group>
</T.Group>

{#if body.orbitElements && !isStar}
	<T.Group bind:ref={orbitWrapRef}>
		<OrbitLine
			elements={body.orbitElements}
			{color}
			bodyPosition={body.position}
			center={body.orbitCenter}
			trailFraction={objType === ObjectType.DWARF_PLANET || objType === ObjectType.MOON
				? 1 / 3
				: undefined}
		/>
	</T.Group>
{/if}
