<script lang="ts">
	import { onMount } from 'svelte';
	import Scene from '../components/Scene.svelte';
	import { fetchHorizons, fetchSmallBodies, fetchSatellites } from '$lib/csv';
	import { orbitalElementsToPosition } from '$lib/kepler';
	import {
		BodyType,
		type HorizonsBody,
		type SmallBody,
		type Satellite,
		type PositionedBody
	} from '$lib/types';
	import { SvelteMap } from 'svelte/reactivity';

	let bodies = $state<PositionedBody<HorizonsBody>[]>([]);
	let smallBodiesList = $state<PositionedBody<SmallBody>[]>([]);
	let satellites = $state<Satellite[]>([]);
	let earthPosition = $state<[number, number, number]>([0, 0, 0]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	onMount(async () => {
		try {
			const [horizons, sbdb, sats] = await Promise.all([
				fetchHorizons(),
				fetchSmallBodies(),
				fetchSatellites()
			]);

			console.log(
				`Loaded: ${horizons.length} horizons bodies, ${sbdb.length} small bodies, ${sats.length} satellites`
			);

			// Position all bodies — parents always appear before children in the list
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
				const offset: [number, number, number] = b.a > 0 ? orbitalElementsToPosition(b) : [0, 0, 0];
				const pos: [number, number, number] = [
					parentPos[0] + offset[0],
					parentPos[1] + offset[1],
					parentPos[2] + offset[2]
				];
				positions.set(b.naifId, pos);
				if (b.type === BodyType.BARYCENTER) {
					barycenters.set(b.naifId, b);
				} else {
					positioned.push({
						data: b,
						position: pos,
						orbitElements: barycenters.get(b.parentNaifId) ?? (b.a > 0 ? b : undefined)
					});
				}
			}
			bodies = positioned;

			// Small bodies are heliocentric — offset from Sun position
			const sunPos = getParentPos(10);
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

			satellites = sats;
			earthPosition = getParentPos(399);

			loading = false;
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
		<Scene {bodies} smallBodies={smallBodiesList} {satellites} {earthPosition} />
	</div>
{/if}
