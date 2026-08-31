<script lang="ts">
	// A planetary system as a SystemMap: moons on a domain in primary radii that
	// follows the system, sized so the largest moon reads at TOP_MOON_R — which
	// keeps moon-against-moon true, the comparison the page is about. Bands are
	// the rings, linking to the primary's Rings tab — except at Earth, where they
	// are the orbit zones and the catalogue rides behind them as a cloud.
	import { getContext, untrack } from 'svelte';
	import SystemMap from './SystemMap.svelte';
	import type { MapBand, SystemMapModel } from './system-map';
	import * as m from '$lib/paraglide/messages.js';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { focusHref, focusClick, isModifiedClick } from '$lib/state/focus-link';
	import { applyGroup, serializeUrl } from '$lib/state/url';
	import { fetchSatOrbitSamples } from '$lib/fetch/groups/sat-orbit-samples';
	import type { EarthOrbitSample } from '$lib/charts/orbit-zones';
	import { EARTH_ID, earthOrbitBands, earthOrbitCloud } from './earth-orbit-bands';
	import type { PlanetarySystemMapData } from './planetary-system.svelte';

	const TOP_MOON_R = 14;
	/** Below this, in primary radii, a band's inner edge *is* the limb. */
	const AT_SURFACE = 1.001;
	const PX_PER_DEG = 0.62;
	/** Axis ticks, in primary radii — the decade ladder, trimmed to the domain. */
	const TICK_LADDER = [1, 2, 3, 5, 10, 20, 30, 50, 100, 200, 300, 500, 1000, 2000, 5000];
	// Tile crop: the primary's limb and the moons nearest it, framed so the
	// baseline rides in the upper third — the card's caption takes the lower half,
	// and moons drawn behind the text read as dirt on the picture.
	const BG_VIEW = '0 96 320 144';
	/** A full-width tile has room for the whole axis, shown whole and centred. */
	const BG_VIEW_WIDE = '0 96 720 144';

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

	function openGroup(slug: string, label: string) {
		return (e: MouseEvent) => {
			if (isModifiedClick(e) || !appState) return;
			e.preventDefault();
			appState.setGroup(slug, label);
		};
	}

	// Earth's orbit zones, as the only system whose primary has a catalogued
	// population of its own. Rings are a band on every other system.
	let bands = $derived.by<MapBand[]>(() => {
		const rKm = system.planetRadiusKm;
		if (isEarth)
			return earthOrbitBands().map((b) => ({
				...b,
				href: appState && serializeUrl(applyGroup(appState.view, b.slug, b.groupLabel)),
				onclick: openGroup(b.slug, b.groupLabel)
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

	// Log domain over the moons and bands actually present, padded a little
	// either side so nothing sits on an edge. A band that reaches the datum keeps
	// the low end unpadded instead: the primary's limb is drawn at the axis
	// origin, and padding below 1 would open a gap between the limb and the
	// lowest orbit above it.
	let domain = $derived.by<[number, number]>(() => {
		let lo = Math.min(...system.moons.map((mn) => mn.aRp));
		let hi = Math.max(...system.moons.map((mn) => mn.aRp));
		for (const b of bands) {
			lo = Math.min(lo, b.innerKm / system.planetRadiusKm);
			hi = Math.max(hi, b.outerKm / system.planetRadiusKm);
		}
		if (hi <= lo) {
			// A lone moon has no span of its own; give it one centred on itself.
			lo /= 2;
			hi *= 2;
		}
		// Snapped, because a band drawn from the datum misses 1 R_p by under a
		// metre — the altitudes are measured from the reference ellipsoid, the
		// axis from the export's triaxial radius.
		lo = lo <= AT_SURFACE ? 1 : lo;
		return [lo > 1 ? 10 ** (Math.log10(lo) - 0.12) : 1, 10 ** (Math.log10(hi) + 0.12)];
	});

	// Sized off the largest *measured* moon: most of a giant's swarm is
	// designation-only with no radius at all, and one of those in the max would
	// take the whole scale to NaN.
	let pxPerKm = $derived(
		TOP_MOON_R / Math.max(...system.moons.map((mn) => mn.radiusKm).filter((r) => r > 0), 1)
	);

	let model = $derived.by<SystemMapModel>(() => {
		const rKm = system.planetRadiusKm;
		const planetId = system.planetId;
		return {
			primary: { id: planetId, name: system.planetName, radiusKm: rKm, color: system.planetColor },
			bodies: system.moons.map((mn) => ({
				id: mn.id,
				name: mn.name,
				aKm: mn.aRp * rKm,
				tiltDeg: mn.tiltDeg,
				radiusKm: mn.radiusKm,
				color: mn.color
			})),
			bands,
			cloud,
			unitKm: rKm,
			domain,
			ticks: TICK_LADDER.filter((t) => t >= domain[0] && t <= domain[1]),
			axisLabel: m.planetary_system_axis_unit(),
			pxPerKm,
			pxPerDeg: PX_PER_DEG,
			backgroundView: wide ? BG_VIEW_WIDE : BG_VIEW,
			backgroundFit: wide ? 'fit' : 'slice'
		};
	});
</script>

<SystemMap {model} {ariaLabel} {variant} />
