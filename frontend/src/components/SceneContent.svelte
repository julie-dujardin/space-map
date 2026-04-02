<script lang="ts">
	import { T, useTask } from '@threlte/core';
	import { OrbitControls, interactivity } from '@threlte/extras';
	import { Vector3 } from 'three';
	import type { OrbitControls as OrbitControlsType } from 'three/addons/controls/OrbitControls.js';
	import { getContext } from 'svelte';
	import Body from './Body.svelte';
	import { type PositionedBody } from '$lib/types/objects';
	import {
		type MapViewState,
		cartesianToSpherical,
		sphericalToCartesian,
		createUrlSync,
		parseUrl
	} from '$lib/url-state';
	import { urlType } from '$lib/format';
	import SmallBodies from './SmallBodies.svelte';
	import type { ContextManager } from '$lib/context-manager.svelte';

	interface Props {
		initialView: MapViewState;
		onFocusChange?: (body: PositionedBody | undefined) => void;
	}

	let { initialView, onFocusChange }: Props = $props();

	interactivity();

	const ctx = getContext<ContextManager>('ctx');

	let controlsRef = $state<OrbitControlsType>();

	// Resolve initial focus body from URL (fall back to Sun)
	const allBodies = ctx.allBodies;
	const matchedBody = allBodies.find(
		(b) => urlType(b.data.objectType) === initialView.type && b.data.id === initialView.id
	);
	const sunBody = ctx.majorBodies.find((b) => b.data.id === 10);
	const initialFocusPos: [number, number, number] = matchedBody?.position ??
		sunBody?.position ?? [0, 0, 0];
	onFocusChange?.(matchedBody);
	const initialFocusBody = matchedBody ?? sunBody;

	if (initialFocusBody) ctx.setFocused(initialFocusBody);
	ctx.updateCamera(initialView.zoom);

	let focusTarget = $state<[number, number, number]>(initialFocusPos);
	let focusedBody = $state<PositionedBody | undefined>(initialFocusBody);

	// Compute initial camera position from URL spherical coords
	const initialCameraPos = sphericalToCartesian(
		initialFocusPos,
		initialView.latitude,
		initialView.longitude,
		initialView.zoom
	);

	const targetVec = new Vector3();
	const urlSync = createUrlSync(300);
	let animating = $state(false);
	let firstFrame = true;

	useTask(() => {
		if (!controlsRef) return;

		// Snap to target on first frame (no lerp animation on load)
		if (firstFrame) {
			firstFrame = false;
			controlsRef.target.set(...focusTarget);
			controlsRef.update();
		}

		targetVec.set(...focusTarget);
		const isAnimating = controlsRef.target.distanceToSquared(targetVec) > 0.0001;
		if (isAnimating) {
			controlsRef.target.lerp(targetVec, 0.08);
			animating = true;
		} else {
			controlsRef.target.copy(targetVec);
			animating = false;
		}
		controlsRef.update();

		// Compute distance every frame (including during animation) for visibility decisions
		if (focusedBody) {
			const cam = controlsRef.object;
			const { latitude, longitude, distance } = cartesianToSpherical(
				[cam.position.x, cam.position.y, cam.position.z],
				[controlsRef.target.x, controlsRef.target.y, controlsRef.target.z]
			);
			ctx.updateCamera(distance);

			if (!animating) {
				urlSync.sync({
					type: urlType(focusedBody.data.objectType),
					id: focusedBody.data.id,
					name: focusedBody.data.name ?? '',
					date: initialView.date,
					isNow: initialView.isNow,
					latitude,
					longitude,
					zoom: distance
				});
			}
		}
	});

	function handleFocus(body: PositionedBody) {
		urlSync.cancel();
		focusTarget = body.position;
		focusedBody = body;
		ctx.setFocused(body);
		onFocusChange?.(body);
	}

	// Handle browser back/forward
	$effect(() => {
		const onPopState = () => {
			const parsed = parseUrl();
			if (!parsed) return;
			const body = ctx.allBodies.find(
				(b) => urlType(b.data.objectType) === parsed.type && b.data.id === parsed.id
			);
			if (body) {
				focusTarget = body.position;
				focusedBody = body;
				ctx.setFocused(body);
			}
			if (controlsRef) {
				const target = body?.position ?? focusTarget;
				const newCamPos = sphericalToCartesian(
					target,
					parsed.latitude,
					parsed.longitude,
					parsed.zoom
				);
				controlsRef.object.position.set(...newCamPos);
			}
		};
		window.addEventListener('popstate', onPopState);
		return () => window.removeEventListener('popstate', onPopState);
	});
</script>

<T.PerspectiveCamera makeDefault position={initialCameraPos} fov={60} near={0.0001} far={100000}>
	<OrbitControls bind:ref={controlsRef} enableDamping />
</T.PerspectiveCamera>

<T.AmbientLight intensity={0.4} />

{#each ctx.majorBodies as body (body.data.id)}
	<Body {body} onFocus={handleFocus} />
{/each}

{#if ctx.asteroidBodies.length > 0}
	<SmallBodies bodies={ctx.asteroidBodies} />
{/if}

{#each [...ctx.spacecraftByParent.entries()] as [groupParentId, bodies] (groupParentId)}
	<SmallBodies {bodies} {groupParentId} />
{/each}
