<script lang="ts">
	// The Solar System as a SystemMap: Sun + planets + dwarfs on a fixed AU
	// domain, major moons stacked on their planet, the belts as bands.
	import { getContext, untrack } from 'svelte';
	import SystemMap from './SystemMap.svelte';
	import type { MapBody, SystemMapModel } from './system-map';
	import { BODY_COLORS, DEFAULT_BODY_COLOR } from '$lib/constants';
	import { AU_KM } from '$lib/math/units';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { isModifiedClick } from '$lib/state/focus-link';
	import { applyGroup, serializeUrl } from '$lib/state/url';
	import {
		fetchSolarSystemMap,
		type SolarSystemMapFile,
		type SolarSystemMapObject
	} from '$lib/fetch/groups/solar-system-map';

	// Radius px per km, tuned so Jupiter reads at ~16 px. Shared with the Sun,
	// which genuinely dwarfs everything (≈156 px → mostly offscreen).
	const PX_PER_KM = 2.24e-4;
	const PX_PER_DEG = 1.8;
	const DOMAIN: [number, number] = [0.3, 50]; // AU; the Sun (a=0) is framed separately
	const TICKS = [0.3, 1, 3, 10, 30];

	interface Props {
		ariaLabel: string;
		/** Object.id → localized label, overriding the exported English name. */
		localizedNames?: Record<string, string>;
		variant?: 'hero' | 'background';
	}
	let { ariaLabel, localizedNames, variant = 'hero' }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');

	let file = $state<SolarSystemMapFile | null>(null);
	$effect(() => {
		untrack(() =>
			fetchSolarSystemMap()
				.then((f) => (file = f))
				.catch((e) => console.error('Solar system map failed to load', e))
		);
	});

	/** Strip a leading minor-planet designation ("50000 Quaoar" → "Quaoar") and
	 *  tidy ALL-CAPS catalogue names; the localized label wins when present. */
	function displayName(o: SolarSystemMapObject): string {
		const local = localizedNames?.[o.id];
		if (local) return local;
		const stripped = o.name.replace(/^\d+\s+/, '');
		if (stripped === stripped.toUpperCase() && /[A-Z]/.test(stripped))
			return stripped.charAt(0) + stripped.slice(1).toLowerCase();
		return stripped;
	}

	function colorOf(o: SolarSystemMapObject): string {
		return o.color || BODY_COLORS[o.id] || DEFAULT_BODY_COLOR;
	}

	function openGroup(slug: string, label: string) {
		return (e: MouseEvent) => {
			if (isModifiedClick(e) || !appState) return;
			e.preventDefault();
			appState.setGroup(slug, label);
		};
	}

	let model = $derived.by<SystemMapModel | null>(() => {
		if (!file) return null;
		const sun = file.objects.find((o) => o.kind === 'star');
		if (!sun) return null;
		const moons = new Map<string, SolarSystemMapObject[]>();
		for (const o of file.objects) {
			if (o.kind !== 'moon' || !o.parent) continue;
			const g = moons.get(o.parent);
			if (g) g.push(o);
			else moons.set(o.parent, [o]);
		}
		const bodies: MapBody[] = file.objects
			.filter((o) => o.kind !== 'moon' && o.kind !== 'star')
			.map((o) => {
				const sats = moons.get(o.id);
				return {
					id: o.id,
					name: displayName(o),
					aKm: o.a * AU_KM,
					tiltDeg: o.i,
					radiusKm: o.diameter_km / 2,
					color: colorOf(o),
					rings: o.rings,
					satellites: sats?.map((s) => ({
						id: s.id,
						name: displayName(s),
						radiusKm: s.diameter_km / 2,
						color: colorOf(s)
					})),
					satelliteCount: o.moon_count,
					satellitesTab: sats?.some((s) => s.link_parent) ?? false
				};
			});
		return {
			primary: {
				id: sun.id,
				name: displayName(sun),
				radiusKm: sun.diameter_km / 2,
				color: '#ffdd44'
			},
			bodies,
			bands: file.belts.map((b) => ({
				key: b.slug,
				label: b.label,
				innerKm: b.inner_au * AU_KM,
				outerKm: b.outer_au * AU_KM,
				tone: b.kind === 'kuiper_belt' ? 'sky' : 'muted',
				href: appState && serializeUrl(applyGroup(appState.view, b.slug, b.label)),
				onclick: openGroup(b.slug, b.label)
			})),
			unitKm: AU_KM,
			domain: DOMAIN,
			ticks: TICKS,
			axisLabel: 'AU · log',
			pxPerKm: PX_PER_KM,
			pxPerDeg: PX_PER_DEG
		};
	});
</script>

{#if model}
	<SystemMap {model} {ariaLabel} {variant} />
{/if}
