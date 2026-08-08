<script lang="ts">
	/**
	 * Where else this body is listed for what it is made of and what it is
	 * doing — the Structure & Activity pages it is a member of.
	 *
	 * Two at most, because this is a footer to the tab and not a second index,
	 * and picked in the order the tab reads: the shells first, then the heat
	 * that moves through them. Membership is derived from the same fields the
	 * exporter filters on, so a body that would not appear on a page is not
	 * offered one.
	 *
	 * Fewer than two matches falls back to the meta node, which is never a lie
	 * — every body with anything on this tab belongs under it.
	 */
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import {
		CAT_ATMOSPHERES,
		CAT_MAGNETIC_FIELDS,
		CAT_OCEANS,
		CAT_STRUCTURE_ACTIVITY,
		CAT_TECTONICS,
		CAT_TIDAL_HEATING,
		CAT_VOLCANISM
	} from '$lib/fetch/groups/registry';
	import BodyCategoryTile from './BodyCategoryTile.svelte';

	interface Props {
		global: GlobalObjectData | null;
	}
	let { global }: Props = $props();

	const SHOWN = 2;

	/** Ordered as the Structure tab is: what the body is made of, then what is
	 *  still happening in it. Each test mirrors that page's membership rule. */
	const PAGES: { slug: string; has: (g: GlobalObjectData) => boolean }[] = [
		{ slug: CAT_OCEANS, has: (g) => !!g.interior?.layers?.some((l) => l.role === 'ocean') },
		{ slug: CAT_ATMOSPHERES, has: (g) => !!g.atmosphere?.pressure },
		{ slug: CAT_TECTONICS, has: (g) => !!g.activity?.tectonics },
		{ slug: CAT_VOLCANISM, has: (g) => !!g.activity?.volcanism },
		{ slug: CAT_MAGNETIC_FIELDS, has: (g) => !!g.activity?.magnetism?.surface_field_t },
		{ slug: CAT_TIDAL_HEATING, has: (g) => !!g.activity?.tidal }
	];

	let slugs = $derived.by(() => {
		if (!global) return [];
		const matched = PAGES.filter((p) => p.has(global)).map((p) => p.slug);
		return matched.length >= SHOWN
			? matched.slice(0, SHOWN)
			: [...matched, CAT_STRUCTURE_ACTIVITY].slice(0, SHOWN);
	});
</script>

{#if slugs.length > 0}
	<div class="grid grid-cols-2 gap-2">
		{#each slugs as slug (slug)}
			<BodyCategoryTile {slug} class={slugs.length === 1 ? 'col-span-2' : ''} />
		{/each}
	</div>
{/if}
