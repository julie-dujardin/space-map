<script lang="ts">
	import {
		CAT_ASTEROIDS,
		CAT_COMETS,
		CAT_DWARF_PLANETS,
		CAT_MOONS,
		CAT_PLANETS,
		CAT_PROBES,
		CAT_SATELLITES
	} from '$lib/fetch/groups/registry';
	import { EARTH_ID } from '$lib/constants';
	import BodyCategoryTile from './BodyCategoryTile.svelte';
	import BodyTile from './BodyTile.svelte';

	interface Props {
		/** The category whose page this is; its siblings are linked. */
		slug: string;
	}
	let { slug }: Props = $props();

	// Sibling categories each page cross-links to, so a visitor can hop between
	// neighbouring collections. Dwarf planets bridge the planet/moon lineups and
	// the asteroid/comet small-body pages; satellites and probes bridge each other.
	const SIBLINGS: Record<string, string[]> = {
		[CAT_PLANETS]: [CAT_DWARF_PLANETS, CAT_MOONS],
		[CAT_DWARF_PLANETS]: [CAT_PLANETS, CAT_ASTEROIDS],
		[CAT_MOONS]: [CAT_PLANETS, CAT_DWARF_PLANETS],
		[CAT_ASTEROIDS]: [CAT_COMETS, CAT_DWARF_PLANETS],
		[CAT_COMETS]: [CAT_ASTEROIDS, CAT_DWARF_PLANETS],
		[CAT_SATELLITES]: [CAT_PROBES],
		[CAT_PROBES]: [CAT_SATELLITES]
	};
	let siblings = $derived(SIBLINGS[slug] ?? []);
	// Satellites orbit Earth — offer a hop to the planet itself.
	let showEarth = $derived(slug === CAT_SATELLITES);
	let tileCount = $derived(siblings.length + (showEarth ? 1 : 0));
	let span = $derived(tileCount === 1 ? 'col-span-2' : '');
</script>

{#if tileCount > 0}
	<div class="grid grid-cols-2 gap-2">
		{#each siblings as s (s)}
			<BodyCategoryTile slug={s} class={span} />
		{/each}
		{#if showEarth}
			<BodyTile id={EARTH_ID} />
		{/if}
	</div>
{/if}
