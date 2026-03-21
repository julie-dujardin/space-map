<script lang="ts">
	import { T, useTask } from '@threlte/core';
	import { OrbitControls, interactivity } from '@threlte/extras';
	import { Vector3 } from 'three';
	import type { OrbitControls as OrbitControlsType } from 'three/addons/controls/OrbitControls.js';
	import Body from './Body.svelte';
	import type { PositionedBody } from '$lib/types';
	import {
		type MapViewState,
		cartesianToSpherical,
		sphericalToCartesian,
		createUrlSync,
		parseUrl
	} from '$lib/url-state';
	import { urlType } from '$lib/format';
	import SmallBodies from './SmallBodies.svelte';

	interface Props {
		majorBodies: PositionedBody[];
		minorBodies: PositionedBody[];
		initialView: MapViewState;
		onFocusChange?: (body: PositionedBody | undefined) => void;
	}

	let { majorBodies, minorBodies, initialView, onFocusChange }: Props = $props();

	interactivity();

	let controlsRef = $state<OrbitControlsType>();

	// Resolve initial focus body from URL (fall back to Sun)
	const allBodies = [...majorBodies, ...minorBodies];
	const matchedBody = allBodies.find(
		(b) => urlType(b.data.objectType) === initialView.type && b.data.id === initialView.id
	);
	const sunBody = majorBodies.find((b) => b.data.id === 10);
	const initialFocusPos: [number, number, number] = matchedBody?.position ??
		sunBody?.position ?? [0, 0, 0];
	const initialFocusBody = matchedBody ?? sunBody;

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

		// Only sync URL when not animating
		if (!animating && focusedBody) {
			const cam = controlsRef.object;
			const { latitude, longitude, distance } = cartesianToSpherical(
				[cam.position.x, cam.position.y, cam.position.z],
				[controlsRef.target.x, controlsRef.target.y, controlsRef.target.z]
			);
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
	});

	function handleFocus(body: PositionedBody) {
		urlSync.cancel();
		focusTarget = body.position;
		focusedBody = body;
		onFocusChange?.(body);
	}

	// Handle browser back/forward
	$effect(() => {
		const onPopState = () => {
			const parsed = parseUrl();
			if (!parsed) return;
			const body = allBodies.find(
				(b) => urlType(b.data.objectType) === parsed.type && b.data.id === parsed.id
			);
			if (body) {
				focusTarget = body.position;
				focusedBody = body;
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

{#each majorBodies as body (body.data.id)}
	<Body {body} onFocus={handleFocus} />
{/each}

{#if minorBodies.length > 0}
	<SmallBodies bodies={minorBodies} />
{/if}
