<script lang="ts">
	import { onMount } from 'svelte';
	import Scene from '../../components/Scene.svelte';
	import { fetchHorizons, fetchSmallBodies, fetchSatellites } from '$lib/csv';
	import { orbitalElementsToPosition } from '$lib/kepler';
	import {
		BodyType,
		type HorizonsBody,
		type SmallBody,
		type Satellite,
		type PositionedBody
	} from '$lib/types';
	import { parseUrl, DEFAULT_VIEW, type MapViewState } from '$lib/url-state';
	import { SvelteMap } from 'svelte/reactivity';

	let bodies = $state<PositionedBody<HorizonsBody>[]>([]);
	let smallBodiesList = $state<PositionedBody<SmallBody>[]>([]);
	let satellites = $state<Satellite[]>([]);
	let earthPosition = $state<[number, number, number]>([0, 0, 0]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	const initialView: MapViewState = parseUrl(window.location.pathname) ?? DEFAULT_VIEW;

	onMount(async () => {
		// Start all fetches immediately (network in parallel)
		const horizonsPromise = fetchHorizons();
		const smallBodiesPromise = fetchSmallBodies();
		const satellitesPromise = fetchSatellites();

		try {
			// Phase 1: await and process horizons (critical path)
			const horizons = await horizonsPromise;
			console.log(`Loaded: ${horizons.length} horizons bodies`);

			const positions = new SvelteMap<number, [number, number, number]>();
			positions.set(0, [0, 0, 0]); // Solar System Barycenter

			function getParentPos(parentNaifId: number): [number, number, number] {
				const pos = positions.get(parentNaifId);
				if (!pos) throw new Error(`Parent ${parentNaifId} not found`);
				return pos;
			}

			const barycenters = new SvelteMap<number, HorizonsBody>();
			const positioned: PositionedBody<HorizonsBody>[] = [];
			for (const b of horizons) {
				const parentPos = getParentPos(b.parentNaifId);
				if (b.a <= 0) {
					// Skip invalid orbits (some probes with no elements like voyagers)
					continue;
				}
				const offset: [number, number, number] = orbitalElementsToPosition(b);
				const pos: [number, number, number] = [
					parentPos[0] + offset[0],
					parentPos[1] + offset[1],
					parentPos[2] + offset[2]
				];
				positions.set(b.naifId, pos);
				if (b.type === BodyType.BARYCENTER) {
					barycenters.set(b.naifId, b);
				} else {
					const isMoon = b.type === BodyType.MOON;
					positioned.push({
						data: b,
						position: pos,
						orbitElements: isMoon
							? b.a > 0
								? b
								: undefined
							: (barycenters.get(b.parentNaifId) ?? (b.a > 0 ? b : undefined)),
						orbitCenter: isMoon ? parentPos : undefined
					});
				}
			}
			bodies = positioned;
			earthPosition = getParentPos(399);
			loading = false; // Scene renders now

			// Phase 2: secondary data (non-blocking)
			const sunPos = getParentPos(10);

			smallBodiesPromise
				.then((sbdb) => {
					console.log(`Loaded: ${sbdb.length} small bodies`);
					smallBodiesList = sbdb
						.filter((b) => b.e < 1 && b.a > 0)
						.map((b) => {
							const offset = orbitalElementsToPosition(b);
							return {
								data: b,
								position: [sunPos[0] + offset[0], sunPos[1] + offset[1], sunPos[2] + offset[2]] as [
									number,
									number,
									number
								]
							};
						});
				})
				.catch((e) => console.warn('Failed to load small bodies:', e));

			satellitesPromise
				.then((sats) => {
					console.log(`Loaded: ${sats.length} satellites`);
					satellites = sats;
				})
				.catch((e) => console.warn('Failed to load satellites:', e));
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			loading = false;
		}
	});
</script>

<svelte:head>
	<title>Space Map</title>
</svelte:head>

{#if loading}
	<div class="flex items-center justify-center h-screen bg-bg text-text">Loading data...</div>
{:else if error}
	<div class="flex items-center justify-center h-screen bg-bg text-text-error">Error: {error}</div>
{:else}
	<div class="w-full h-screen">
		<Scene {bodies} smallBodies={smallBodiesList} {satellites} {earthPosition} {initialView} />
	</div>
{/if}
