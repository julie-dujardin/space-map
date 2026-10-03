<script lang="ts">
	// A planetary system as a SystemMap, every target leading to its page. Bands
	// are the rings, linking to the primary's Rings tab — except at Earth, where
	// they are the orbit zones and the catalogue rides behind them as a cloud.
	import { getContext, untrack } from 'svelte';
	import SystemMap from './SystemMap.svelte';
	import { siteMapText } from './system-map-text';
	import type { MapBand } from '$lib/systemmap/model';
	import { planetarySystemModel, type PlanetarySystemMapData } from '$lib/systemmap/planetary';
	import * as m from '$lib/paraglide/messages.js';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { focusHref, focusClick, groupClick, groupHref } from '$lib/state/focus-link';
	import { fetchSatOrbitSamples } from '$lib/fetch/groups/sat-orbit-samples';
	import type { EarthOrbitSample } from '$lib/charts/orbit-zones';
	import { EARTH_ID, earthOrbitBands, earthOrbitCloud } from './earth-orbit-bands';

	interface Props {
		system: PlanetarySystemMapData;
		ariaLabel: string;
		variant?: 'hero' | 'background';
		/** Background on a tile spanning the row: the whole axis fits. */
		wide?: boolean;
	}
	let { system, ariaLabel, variant = 'hero', wide = false }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	let isEarth = $derived(system.planetId === EARTH_ID);

	// Earth's orbit zones, as the only system whose primary has a catalogued
	// population of its own. Rings are a band on every other system.
	let bands = $derived.by<MapBand[]>(() => {
		const rKm = system.planetRadiusKm;
		if (isEarth)
			return earthOrbitBands().map((b) => ({
				...b,
				href: groupHref(appState, b.slug, b.groupLabel),
				onclick: groupClick(appState, b.slug, b.groupLabel)
			}));
		if (!system.rings) return [];
		return [
			{
				key: 'rings',
				label: m.tab_rings(),
				innerKm: system.rings.innerRp * rKm,
				outerKm: system.rings.outerRp * rKm,
				tone: 'amber',
				href: focusHref(appState, system.planetId, system.planetName, 'rings'),
				onclick: focusClick(focusObject, system.planetId, system.planetName, { tab: 'rings' })
			}
		];
	});

	// The satellite catalogue, fetched only for the one map that draws it.
	let samples = $state<EarthOrbitSample[] | null>(null);
	$effect(() => {
		if (!isEarth) return;
		untrack(() =>
			fetchSatOrbitSamples()
				.then((s) => (samples = s))
				.catch((e) => console.error('Sat orbit samples failed to load', e))
		);
	});
	let cloud = $derived(samples ? earthOrbitCloud(samples) : undefined);

	const focusLink = (id: string, name: string) => ({
		href: focusHref(appState, id, name),
		onclick: focusClick(focusObject, id, name)
	});

	let model = $derived(
		planetarySystemModel(system, {
			text: siteMapText(),
			axisLabel: m.planetary_system_axis_unit(),
			bands,
			cloud,
			primaryLink: focusLink(system.planetId, system.planetName),
			moonLink: (moon) => focusLink(moon.id, moon.name),
			wide
		})
	);
</script>

<SystemMap {model} {ariaLabel} {variant} />
