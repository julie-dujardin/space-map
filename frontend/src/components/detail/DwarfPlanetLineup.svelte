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

	// Tilt + oblateness for the two textured dwarf planets (rendering only); the
	// rest render as flat spheres. Sizes come from the export's diameter_km.
	const TEXTURED: Record<string, Pick<LineupBody, 'polarRatio' | 'poleRa' | 'poleDec'>> = {
		'naif-999': { polarRatio: 1.0, poleRa: 132.993, poleDec: -6.163 }, // Pluto
		'naif-2000001': { polarRatio: 0.925, poleRa: 291.418, poleDec: 66.764 } // Ceres
	};

	let bodies = $derived.by<LineupBody[]>(() => {
		const out: LineupBody[] = [];
		for (const mm of members) {
			if (!mm.id || mm.diameter_km == null) continue;
			out.push({
				id: mm.id,
				name: localizedNames?.[mm.id] ?? mm.name,
				description: localizedDescriptions?.[mm.id],
				radiusKm: mm.diameter_km / 2,
				...(TEXTURED[mm.id] ?? {})
			});
		}
		return out;
	});
</script>

<BodyLineup {bodies} ariaLabel={m.type_dwarf_planet()} perPage={5} />
