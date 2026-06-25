<script lang="ts">
	import type { NotableMemberEntry } from '$lib/fetch/groups/details';
	import * as m from '$lib/paraglide/messages.js';
	import BodyLineup, { type LineupBody } from './BodyLineup.svelte';

	interface Props {
		members: NotableMemberEntry[];
		localizedNames?: Record<string, string>;
	}
	let { members, localizedNames }: Props = $props();

	// Per-planet geometry from the export's PCK radii/poles. Category
	// `notable_members` carry no geometry, so the lineup sizes off these
	// constants; the key set doubles as the planet filter. Equatorial radius km
	// (`radii.a`), polar ratio (c/a oblateness), IAU pole RA/Dec (obliquity).
	const PLANETS: Record<string, Omit<LineupBody, 'id' | 'name'>> = {
		'naif-199': { radiusKm: 2440.53, polarRatio: 0.99907, poleRa: 281.0103, poleDec: 61.4155 },
		'naif-299': {
			radiusKm: 6051.8,
			polarRatio: 1.0,
			poleRa: 272.76,
			poleDec: 67.16,
			cloudSystem: 'naif-2'
		},
		'naif-399': {
			radiusKm: 6378.14,
			polarRatio: 0.996646,
			poleRa: 0,
			poleDec: 90,
			surfaceFrame: '06',
			cloudSystem: 'naif-3'
		},
		'naif-499': { radiusKm: 3396.19, polarRatio: 0.994114, poleRa: 317.269202, poleDec: 54.432516 },
		'naif-599': { radiusKm: 71492, polarRatio: 0.935126, poleRa: 268.056595, poleDec: 64.495303 },
		'naif-699': { radiusKm: 60268, polarRatio: 0.902037, poleRa: 40.589, poleDec: 83.537 },
		'naif-799': { radiusKm: 25559, polarRatio: 0.97707, poleRa: 257.311, poleDec: -15.175 },
		'naif-899': { radiusKm: 24764, polarRatio: 0.982918, poleRa: 299.36, poleDec: 43.46 }
	};

	let bodies = $derived.by<LineupBody[]>(() => {
		const byId = new Map(members.filter((mm) => mm.id).map((mm) => [mm.id as string, mm]));
		const out: LineupBody[] = [];
		for (const [id, geom] of Object.entries(PLANETS)) {
			const mm = byId.get(id);
			if (!mm) continue;
			out.push({ id, name: localizedNames?.[id] ?? mm.name, ...geom });
		}
		return out;
	});
</script>

<BodyLineup {bodies} ariaLabel={m.type_planet()} />
