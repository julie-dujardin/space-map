<script lang="ts">
	import { onMount } from 'svelte';
	import Scene from '../../../components/Scene.svelte';
	import { fetchElements, type ElementColumns } from '$lib/elements';
	import { fetchLabels } from '$lib/labels';
	import { orbitalElementsToPosition } from '$lib/kepler';
	import { ObjectType, Scale, isMajorBody } from '$lib/format';
	import { type BodyData, type PositionedBody, type OrbitalElements } from '$lib/types';
	import { parseUrl, DEFAULT_VIEW, type MapViewState } from '$lib/url-state';

	const KM_PER_AU = 149_597_870.7;

	let majorBodies = $state<PositionedBody[]>([]);
	let minorBodies = $state<PositionedBody[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	const initialView: MapViewState = parseUrl() ?? DEFAULT_VIEW;

	function columnarToBody(
		cols: ElementColumns,
		idx: number,
		labels: Map<number, string>
	): BodyData {
		const isPlanetScale = cols.scale[idx] === Scale.PLANET;

		return {
			eid: cols.eid[idx],
			name: labels.get(cols.eid[idx]) ?? null,
			objectType: cols.objectType[idx] as ObjectType,
			naifId: cols.naifId[idx],
			parentNaifId: cols.parentNaifId[idx],
			radiusKm: cols.radiusKm[idx],
			// Planet-scale: a is in km, n is in rev/day → convert to AU and deg/day
			a: isPlanetScale ? cols.a[idx] / KM_PER_AU : cols.a[idx],
			e: cols.e[idx],
			i: cols.i[idx],
			om: cols.om[idx],
			w: cols.w[idx],
			ma: cols.ma[idx],
			n: isPlanetScale ? cols.n[idx] * 360 : cols.n[idx],
			epoch: cols.epochJd[idx]
		};
	}

	onMount(async () => {
		try {
			const [cols, labels] = await Promise.all([fetchElements(), fetchLabels()]);

			console.log(`Loaded: ${cols.rowCount} objects`);

			// Track positions by NAIF ID for parent lookups (not reactive — local computation only)
			// eslint-disable-next-line svelte/prefer-svelte-reactivity
			const positions = new Map<number, [number, number, number]>();
			positions.set(0, [0, 0, 0]); // Solar System Barycenter

			// Store barycenter orbital elements for planet orbit drawing
			// eslint-disable-next-line svelte/prefer-svelte-reactivity
			const barycenters = new Map<number, OrbitalElements>();

			const major: PositionedBody[] = [];
			const minor: PositionedBody[] = [];

			for (let idx = 0; idx < cols.rowCount; idx++) {
				const a = cols.a[idx];
				const e = cols.e[idx];
				if (!(a > 0) || e >= 1) continue; // skip invalid orbits

				const parentNaifId = cols.parentNaifId[idx];
				const parentPos = positions.get(parentNaifId) ?? positions.get(0)!;

				const body = columnarToBody(cols, idx, labels);
				const offset = orbitalElementsToPosition(body, initialView.date);
				const pos: [number, number, number] = [
					parentPos[0] + offset[0],
					parentPos[1] + offset[1],
					parentPos[2] + offset[2]
				];

				// Store position by NAIF ID for child lookups
				const naifId = cols.naifId[idx];
				if (naifId !== -1) {
					positions.set(naifId, pos);
				}

				const objType = cols.objectType[idx] as ObjectType;

				if (objType === ObjectType.BARYCENTER || objType === ObjectType.LAGRANGE_POINT) {
					// Barycenters: store elements for planet orbit drawing, don't render
					barycenters.set(naifId, body);
					continue;
				}

				if (isMajorBody(objType)) {
					const isMoon = objType === ObjectType.MOON;
					major.push({
						data: body,
						position: pos,
						orbitElements: isMoon ? body : (barycenters.get(parentNaifId) ?? body),
						orbitCenter: isMoon ? parentPos : undefined
					});
				} else {
					minor.push({
						data: body,
						position: pos
					});
				}
			}

			majorBodies = major;
			minorBodies = minor;
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
		<Scene {majorBodies} {minorBodies} {initialView} />
	</div>
{/if}
