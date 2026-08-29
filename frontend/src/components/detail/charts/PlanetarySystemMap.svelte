<script lang="ts">
	// A planetary system as a SystemMap: moons on a domain in primary radii that
	// follows the system, sized so the largest moon reads at TOP_MOON_R — which
	// keeps moon-against-moon true, the comparison the page is about. The rings
	// are a band linking to the primary's Rings tab.
	import { getContext } from 'svelte';
	import SystemMap from './SystemMap.svelte';
	import type { SystemMapModel } from './system-map';
	import * as m from '$lib/paraglide/messages.js';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { focusHref, focusClick } from '$lib/state/focus-link';
	import type { PlanetarySystemMapData } from './planetary-system.svelte';

	const TOP_MOON_R = 14;
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

	// Log domain over the moons actually present, widened to take in the rings and
	// padded a little either side so nothing sits on an edge.
	let domain = $derived.by<[number, number]>(() => {
		let lo = Math.min(...system.moons.map((mn) => mn.aRp));
		let hi = Math.max(...system.moons.map((mn) => mn.aRp));
		if (system.rings) {
			lo = Math.min(lo, system.rings.innerRp);
			hi = Math.max(hi, system.rings.outerRp);
		}
		if (hi <= lo) {
			// A lone moon has no span of its own; give it one centred on itself.
			lo /= 2;
			hi *= 2;
		}
		lo = Math.max(1, lo);
		return [10 ** (Math.log10(lo) - 0.12), 10 ** (Math.log10(hi) + 0.12)];
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
			bands: system.rings
				? [
						{
							key: 'rings',
							label: m.tab_rings(),
							innerKm: system.rings.innerRp * rKm,
							outerKm: system.rings.outerRp * rKm,
							tone: 'amber',
							href: focusHref(appState, planetId, system.planetName, 'rings'),
							onclick: focusClick(focusObject, planetId, system.planetName, { tab: 'rings' })
						}
					]
				: [],
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
