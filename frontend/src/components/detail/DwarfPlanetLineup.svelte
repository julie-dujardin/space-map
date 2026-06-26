<script lang="ts">
	import type { NotableMemberEntry } from '$lib/fetch/groups/details';
	import * as m from '$lib/paraglide/messages.js';
	import BodyLineup, { type LineupBody } from './BodyLineup.svelte';

	interface Props {
		members: NotableMemberEntry[];
		localizedNames?: Record<string, string>;
		localizedDescriptions?: Record<string, string>;
	}
	let { members, localizedNames, localizedDescriptions }: Props = $props();

	// Per-body geometry for the lineup; the key set doubles as the dwarf-planet
	// filter (category notable_members carry no geometry). Radii are the quoted
	// mean radius km — volume-equivalent for the very triaxial bodies (Haumea),
	// since the engine renders a single scaled sphere and can't show triaxiality.
	// Only Pluto + Ceres ship textures and have IAU poles/oblateness; the rest
	// render as flat spheres (see BODY_COLORS), so they omit pole/polarRatio.
	const DWARF_PLANETS: Record<string, Omit<LineupBody, 'id' | 'name'>> = {
		'naif-999': { radiusKm: 1188.3, polarRatio: 1.0, poleRa: 132.993, poleDec: -6.163 }, // Pluto
		'spkid-20136199': { radiusKm: 1163 }, // Eris
		'naif-2000001': { radiusKm: 482.1, polarRatio: 0.925, poleRa: 291.418, poleDec: 66.764 }, // Ceres
		'spkid-20136108': { radiusKm: 798 }, // Haumea (volume-equivalent)
		'spkid-20136472': { radiusKm: 715 }, // Makemake
		'spkid-20225088': { radiusKm: 615 }, // Gonggong
		'spkid-20050000': { radiusKm: 545 }, // Quaoar
		'spkid-20090377': { radiusKm: 500 }, // Sedna
		'spkid-20090482': { radiusKm: 458 }, // Orcus
		'spkid-20120347': { radiusKm: 423 } // Salacia
	};

	let bodies = $derived.by<LineupBody[]>(() => {
		const byId = new Map(members.filter((mm) => mm.id).map((mm) => [mm.id as string, mm]));
		const out: LineupBody[] = [];
		for (const [id, geom] of Object.entries(DWARF_PLANETS)) {
			const mm = byId.get(id);
			if (!mm) continue;
			out.push({
				id,
				name: localizedNames?.[id] ?? mm.name,
				description: localizedDescriptions?.[id],
				...geom
			});
		}
		return out;
	});
</script>

<BodyLineup {bodies} ariaLabel={m.type_dwarf_planet()} perPage={5} />
