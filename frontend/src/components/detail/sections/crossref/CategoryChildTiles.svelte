<script lang="ts">
	/**
	 * A category's children, two across.
	 *
	 * The tiles are `PropertyTile`, so the Structure & Activity child draws the
	 * same two cut-open worlds here as it does on its own page and in a body's
	 * Structure-tab crossrefs; everything else keeps its lead image.
	 */
	import type { ChildGroupEntry } from '$lib/fetch/groups/details';
	import { categoryLabel, CATEGORY_SLUG_PREFIX } from '$lib/fetch/groups/registry';
	import { classNameFromSlug, orbitClassLabel } from '$lib/charts/orbit-zones';
	import PropertyTile from './PropertyTile.svelte';

	interface Props {
		childGroups: ChildGroupEntry[];
		/** One tile per row, each with the full four drawings. Structure &
		 *  Activity takes this: every one of its children is a drawn collection,
		 *  so the tiles are the page rather than a footer to it. */
		wide?: boolean;
	}
	let { childGroups, wide = false }: Props = $props();

	// Category / orbit-class names come from i18n keys (the export name is
	// English-only there); other groups keep the export name. Mirrors ChildGroups.
	function childName(c: ChildGroupEntry): string {
		const slug = c.primary_id ?? '';
		if (slug.startsWith(CATEGORY_SLUG_PREFIX)) return categoryLabel(slug);
		const className = classNameFromSlug(slug);
		return className != null ? orbitClassLabel(className) : c.name;
	}

	let tiles = $derived(childGroups.filter((c) => c.primary_id));
	// An odd count leaves the last tile alone on its row — widen it rather than
	// letting it sit half-width. Mirrors CategoryCrossRefs.
	let wideIndex = $derived(tiles.length % 2 === 1 ? tiles.length - 1 : -1);
	/** The drawings follow the width: four across a tile that spans the row, two
	 *  where four 44 px discs would crowd the name out of a half-width one. */
	function drawings(i: number): number {
		return wide || i === wideIndex ? 4 : 2;
	}
</script>

{#if tiles.length > 0}
	<div class="grid gap-2" class:grid-cols-2={!wide}>
		{#each tiles as c, i (c.primary_id)}
			<PropertyTile
				slug={c.primary_id ?? ''}
				name={childName(c)}
				n={c.n}
				shown={drawings(i)}
				class={!wide && i === wideIndex ? 'col-span-2' : ''}
			/>
		{/each}
	</div>
{/if}
