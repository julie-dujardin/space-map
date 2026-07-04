<script lang="ts">
	import {
		CAT_ASTEROIDS,
		CAT_COMETS,
		CAT_DWARF_PLANETS,
		CAT_MOONS,
		CAT_PLANETS
	} from '$lib/fetch/groups/registry';
	import BodyCategoryTile from './BodyCategoryTile.svelte';

	interface Props {
		/** The category whose page this is; its siblings are linked. */
		slug: string;
	}
	let { slug }: Props = $props();

	// Sibling categories each page cross-links to, so a visitor can hop between
	// neighbouring collections. Dwarf planets bridge the planet/moon lineups and
	// the asteroid/comet small-body pages.
	const SIBLINGS: Record<string, string[]> = {
		[CAT_PLANETS]: [CAT_DWARF_PLANETS, CAT_MOONS],
		[CAT_DWARF_PLANETS]: [CAT_PLANETS, CAT_ASTEROIDS],
		[CAT_MOONS]: [CAT_PLANETS, CAT_DWARF_PLANETS],
		[CAT_ASTEROIDS]: [CAT_COMETS, CAT_DWARF_PLANETS],
		[CAT_COMETS]: [CAT_ASTEROIDS, CAT_DWARF_PLANETS]
	};
	let siblings = $derived(SIBLINGS[slug] ?? []);
</script>

{#if siblings.length > 0}
	<div class="grid grid-cols-2 gap-2">
		{#each siblings as s (s)}
			<BodyCategoryTile slug={s} />
		{/each}
	</div>
{/if}
