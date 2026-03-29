<script lang="ts">
	import { onMount } from 'svelte';
	import Scene from '../../../../components/Scene.svelte';
	import { fetchElements, type ElementColumns } from '$lib/elements';
	import { fetchLabels } from '$lib/labels';
	import { orbitalElementsToPosition } from '$lib/kepler';
	import { ObjectType, Scale, isMajorBody } from '$lib/format';
	import { type BodyData, type PositionedBody, type OrbitalElements } from '$lib/types';
	import { parseUrl, DEFAULT_VIEW, type MapViewState } from '$lib/url-state';
	import ObjectDrawer from '../../../../components/detail/ObjectDrawer.svelte';
	import * as m from '$lib/paraglide/messages.js';

	const KM_PER_AU = 149_597_870.7;

	let majorBodies = $state<PositionedBody[]>([]);
	let minorBodies = $state<PositionedBody[]>([]);
	let selectedBody = $state<PositionedBody | undefined>();
	let loading = $state(true);
	let error = $state<string | null>(null);

	const initialView: MapViewState = parseUrl() ?? DEFAULT_VIEW;

	function columnarToBody(
		cols: ElementColumns,
		idx: number,
		labels: Map<number, string>,
		idMap: Record<string, string>
	): BodyData {
		const isPlanetScale = cols.scale[idx] === Scale.PLANET;

		return {
			id: cols.id[idx],
			fileId: idMap[idx] ?? null,
			name: labels.get(idx) ?? null,
			objectType: cols.objectType[idx] as ObjectType,
			parentId: cols.parentId[idx],
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
			const [cols, labels, idMap] = await Promise.all([
				fetchElements(),
				fetchLabels(),
				fetch('/data/v1/id_map.json').then((r) => {
					if (!r.ok) throw new Error(`id_map.json: ${r.status} ${r.statusText}`);
					return r.json() as Promise<Record<string, string>>;
				})
			]);

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
				const objType = cols.objectType[idx] as ObjectType;

				if (!(a > 0) || e >= 1) {
					if (
						isMajorBody(objType) ||
						objType === ObjectType.BARYCENTER ||
						objType === ObjectType.LAGRANGE_POINT
					) {
						// Major bodies with near-zero orbits (e.g. planets at their barycenter) are
						// still valid — they sit at the parent position with zero offset.
						console.debug(
							`Body idx=${idx} id=${cols.id[idx]} (${ObjectType[objType]}) has a=${a} e=${e}, keeping as major body`
						);
					} else {
						console.debug(
							`Skipping idx=${idx} id=${cols.id[idx]} (${ObjectType[objType]}): invalid orbit a=${a} e=${e}`
						);
						continue;
					}
				}

				const parentId = cols.parentId[idx];
				const parentPos = positions.get(parentId) ?? positions.get(0)!;

				const body = columnarToBody(cols, idx, labels, idMap);
				const offset = orbitalElementsToPosition(body, initialView.date);
				const pos: [number, number, number] = [
					parentPos[0] + offset[0],
					parentPos[1] + offset[1],
					parentPos[2] + offset[2]
				];

				const id = cols.id[idx];

				// Store position by ID for child lookups (body-type objects use NAIF IDs)
				if (isMajorBody(objType)) {
					positions.set(id, pos);
				}

				if (objType === ObjectType.BARYCENTER || objType === ObjectType.LAGRANGE_POINT) {
					// Barycenters: store elements for planet orbit drawing, don't render
					barycenters.set(id, body);
					positions.set(id, pos);
					continue;
				}

				if (isMajorBody(objType)) {
					const isMoon = objType === ObjectType.MOON;
					major.push({
						data: body,
						position: pos,
						orbitElements: isMoon ? body : (barycenters.get(parentId) ?? body),
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
	<title
		>{selectedBody?.data.name
			? `${selectedBody.data.name} - ${m.page_title()}`
			: m.page_title()}</title
	>
</svelte:head>

{#if loading}
	<div class="flex items-center justify-center h-screen bg-bg text-text">{m.loading_data()}</div>
{:else if error}
	<div class="flex items-center justify-center h-screen bg-bg text-text-error">
		{m.error_prefix({ error })}
	</div>
{:else}
	<div class="relative w-full h-screen">
		<Scene
			{majorBodies}
			{minorBodies}
			{initialView}
			onFocusChange={(body) => (selectedBody = body)}
		/>
		{#if selectedBody?.data.fileId}
			<ObjectDrawer body={selectedBody} onClose={() => (selectedBody = undefined)} />
		{/if}
	</div>
{/if}
