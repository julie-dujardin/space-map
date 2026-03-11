<script lang="ts">
	import { onMount } from 'svelte';
	import Scene from '../components/Scene.svelte';
	import { fetchHorizons, fetchSmallBodies, fetchSatellites } from '$lib/csv';
	import { orbitalElementsToPosition } from '$lib/kepler';
	import type { HorizonsBody, SmallBody, Satellite, PositionedBody } from '$lib/types';
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

			// First pass: compute positions for planets (heliocentric, no parent)
			const planets = horizons.filter((b) => b.parentNaifId === null && b.a > 0);
			const planetPositions = new SvelteMap<number, [number, number, number]>();
			const positioned: PositionedBody<HorizonsBody>[] = [];

			for (const p of planets) {
				const pos = orbitalElementsToPosition(p);
				planetPositions.set(p.naifId, pos);
				positioned.push({ data: p, position: pos });
			}

			// Second pass: moons — offset from parent planet position
			const moons = horizons.filter((b) => b.parentNaifId !== null && b.a > 0);
			for (const m of moons) {
				const parentPos = planetPositions.get(m.parentNaifId!);
				if (!parentPos) {
					console.warn(`Parent body with NAIF ID ${m.parentNaifId} not found for moon ${m.name}`);
					continue;
				}
				const offset = orbitalElementsToPosition(m);
				positioned.push({
					data: m,
					position: [parentPos[0] + offset[0], parentPos[1] + offset[1], parentPos[2] + offset[2]]
				});
			}

			bodies = positioned;

			smallBodiesList = sbdb
				.filter((b) => b.e < 1 && b.a > 0)
				.map((b) => ({
					data: b,
					position: orbitalElementsToPosition(b)
				}));

			satellites = sats;

			// Find Earth's position for satellite marker
			earthPosition = planetPositions.get(399) ?? [0, 0, 0];

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
	<div class="flex items-center justify-center h-screen bg-black text-white">Loading data...</div>
{:else if error}
	<div class="flex items-center justify-center h-screen bg-black text-red-400">Error: {error}</div>
{:else}
	<div class="w-full h-screen">
		<Scene {bodies} smallBodies={smallBodiesList} {satellites} {earthPosition} />
	</div>
{/if}
