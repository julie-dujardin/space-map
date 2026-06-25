<script lang="ts">
	import type { NotableMemberEntry } from '$lib/fetch/groups/details';
	import * as m from '$lib/paraglide/messages.js';
	import BodyLineup, { type LineupBody } from './BodyLineup.svelte';

	interface Props {
		members: NotableMemberEntry[];
		localizedNames?: Record<string, string>;
	}
	let { members, localizedNames }: Props = $props();

	// Per-moon geometry from the export's PCK radii/poles (the top two dozen by
	// prominence). Category `notable_members` carry no geometry, so the lineup
	// sizes off these constants; the key set doubles as the moon filter.
	// Equatorial radius km (`radii.a`), polar ratio (c/a), IAU pole RA/Dec.
	const MOONS: Record<string, Omit<LineupBody, 'id' | 'name'>> = {
		'naif-301': { radiusKm: 1737.4, polarRatio: 1.0, poleRa: 269.9949, poleDec: 66.5392 }, // Moon
		'naif-606': { radiusKm: 2575.15, polarRatio: 0.99974, poleRa: 39.4827, poleDec: 83.4279 }, // Titan
		'naif-401': { radiusKm: 13.0, polarRatio: 0.7, poleRa: 317.67072, poleDec: 52.88627 }, // Phobos
		'naif-502': { radiusKm: 1562.6, polarRatio: 0.99802, poleRa: 268.08, poleDec: 64.51 }, // Europa
		'naif-501': { radiusKm: 1829.4, polarRatio: 0.99251, poleRa: 268.05, poleDec: 64.5 }, // Io
		'naif-503': { radiusKm: 2631.2, polarRatio: 1.0, poleRa: 268.2, poleDec: 64.57 }, // Ganymede
		'naif-402': { radiusKm: 7.8, polarRatio: 0.65385, poleRa: 316.65706, poleDec: 53.50992 }, // Deimos
		'naif-504': { radiusKm: 2410.3, polarRatio: 1.0, poleRa: 268.72, poleDec: 64.83 }, // Callisto
		'naif-801': { radiusKm: 1352.6, polarRatio: 1.0, poleRa: 299.36, poleDec: 41.17 }, // Triton
		'naif-602': { radiusKm: 256.6, polarRatio: 0.96765, poleRa: 40.66, poleDec: 83.52 }, // Enceladus
		'naif-901': { radiusKm: 606.0, polarRatio: 1.0, poleRa: 132.993, poleDec: -6.163 }, // Charon
		'naif-703': { radiusKm: 788.9, polarRatio: 1.0, poleRa: 257.43, poleDec: -15.1 }, // Titania
		'naif-704': { radiusKm: 761.4, polarRatio: 1.0, poleRa: 257.43, poleDec: -15.1 }, // Oberon
		'naif-601': { radiusKm: 207.8, polarRatio: 0.91723, poleRa: 40.66, poleDec: 83.52 }, // Mimas
		'naif-605': { radiusKm: 765.0, polarRatio: 0.9966, poleRa: 40.38, poleDec: 83.55 }, // Rhea
		'naif-604': { radiusKm: 563.4, polarRatio: 0.99326, poleRa: 40.66, poleDec: 83.52 }, // Dione
		'naif-702': { radiusKm: 584.7, polarRatio: 1.0, poleRa: 257.43, poleDec: -15.1 }, // Umbriel
		'naif-516': { radiusKm: 30.0, polarRatio: 0.56667, poleRa: 268.05, poleDec: 64.49 }, // Metis
		'naif-608': { radiusKm: 745.7, polarRatio: 0.95494, poleRa: 318.16, poleDec: 75.03 }, // Iapetus
		'naif-701': { radiusKm: 581.1, polarRatio: 0.99415, poleRa: 257.43, poleDec: -15.1 }, // Ariel
		'naif-705': { radiusKm: 240.4, polarRatio: 0.9688, poleRa: 257.43, poleDec: -15.08 }, // Miranda
		'naif-505': { radiusKm: 125.0, polarRatio: 0.512, poleRa: 268.05, poleDec: 64.49 }, // Amalthea
		'naif-603': { radiusKm: 538.4, polarRatio: 0.97753, poleRa: 40.66, poleDec: 83.52 }, // Tethys
		'naif-515': { radiusKm: 10.0, polarRatio: 0.7, poleRa: 268.05, poleDec: 64.49 }, // Adrastea
		'naif-514': { radiusKm: 58.0, polarRatio: 0.72414, poleRa: 268.05, poleDec: 64.49 } // Thebe
	};

	let bodies = $derived.by<LineupBody[]>(() => {
		const byId = new Map(members.filter((mm) => mm.id).map((mm) => [mm.id as string, mm]));
		const out: LineupBody[] = [];
		for (const [id, geom] of Object.entries(MOONS)) {
			const mm = byId.get(id);
			if (!mm) continue;
			out.push({ id, name: localizedNames?.[id] ?? mm.name, ...geom });
		}
		return out;
	});
</script>

<BodyLineup {bodies} ariaLabel={m.type_moon()} perPage={5} />
