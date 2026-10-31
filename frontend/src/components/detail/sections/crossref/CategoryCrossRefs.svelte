<script lang="ts">
	import {
		CAT_ASTEROIDS,
		CAT_COMETS,
		CAT_CONSTELLATIONS,
		CAT_DEBRIS,
		CAT_DWARF_PLANETS,
		CAT_MOONS,
		CAT_PLANETARY_SYSTEMS,
		CAT_STAR_SYSTEMS,
		CAT_SATELLITE_SYSTEMS,
		CAT_PLANETS,
		CAT_PROBES,
		CAT_RING_SYSTEMS,
		CAT_SATELLITES,
		CAT_SOLAR_SYSTEM,
		CAT_STARS,
		CAT_STRUCTURE_ACTIVITY,
		CAT_SURFACE_FEATURES
	} from '$lib/fetch/groups/registry';
	import BodyCategoryTile from './BodyCategoryTile.svelte';

	interface Props {
		/** The category whose page this is; its siblings are linked. */
		slug: string;
	}
	let { slug }: Props = $props();

	// Sibling categories each page cross-links to, so a visitor can hop between
	// neighbouring collections. Dwarf planets bridge the planet lineup and the
	// asteroid/comet small-body pages; moons pair with rings, the other thing a
	// system holds in orbit; the three spacecraft collections (satellites,
	// debris, probes) each link to the other two. A page that left the Solar
	// System in the breadcrumb tree keeps it here.
	const SIBLINGS: Record<string, string[]> = {
		[CAT_PLANETS]: [CAT_DWARF_PLANETS, CAT_MOONS],
		[CAT_DWARF_PLANETS]: [CAT_PLANETS, CAT_ASTEROIDS],
		[CAT_SOLAR_SYSTEM]: [CAT_PLANETARY_SYSTEMS],
		[CAT_SATELLITE_SYSTEMS]: [CAT_SOLAR_SYSTEM, CAT_MOONS],
		[CAT_MOONS]: [CAT_SOLAR_SYSTEM, CAT_RING_SYSTEMS],
		[CAT_SURFACE_FEATURES]: [CAT_SOLAR_SYSTEM, CAT_STRUCTURE_ACTIVITY],
		[CAT_STRUCTURE_ACTIVITY]: [CAT_SOLAR_SYSTEM, CAT_SURFACE_FEATURES],
		[CAT_ASTEROIDS]: [CAT_COMETS, CAT_DWARF_PLANETS],
		[CAT_COMETS]: [CAT_ASTEROIDS, CAT_DWARF_PLANETS],
		[CAT_STARS]: [CAT_STAR_SYSTEMS, CAT_CONSTELLATIONS],
		[CAT_STAR_SYSTEMS]: [CAT_STARS, CAT_PLANETARY_SYSTEMS],
		[CAT_PLANETARY_SYSTEMS]: [CAT_STARS, CAT_STAR_SYSTEMS],
		[CAT_CONSTELLATIONS]: [CAT_STARS],
		[CAT_SATELLITES]: [CAT_DEBRIS, CAT_PROBES],
		[CAT_DEBRIS]: [CAT_SATELLITES, CAT_PROBES],
		[CAT_PROBES]: [CAT_SATELLITES, CAT_DEBRIS]
	};
	let siblings = $derived(SIBLINGS[slug] ?? []);
	// An odd count leaves the last tile alone on its row — widen it rather than
	// letting it sit half-width. Mirrors CategoryChildTiles.
	let wideIndex = $derived(siblings.length % 2 === 1 ? siblings.length - 1 : -1);
</script>

{#if siblings.length > 0}
	<div class="grid grid-cols-2 gap-2">
		{#each siblings as s, i (s)}
			<BodyCategoryTile slug={s} class={i === wideIndex ? 'col-span-2' : ''} />
		{/each}
	</div>
{/if}
