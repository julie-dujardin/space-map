<script lang="ts">
	import type { ChildGroupEntry } from '$lib/fetch/groups/details';
	import { categoryLabel, CATEGORY_SLUG_PREFIX } from '$lib/fetch/groups/registry';
	import { classNameFromSlug, orbitClassLabel } from '$lib/charts/orbit-zones';
	import { formatCompactNumber } from '$lib/format/quantities';
	import * as m from '$lib/paraglide/messages.js';
	import GroupTile from './GroupTile.svelte';

	interface Props {
		childGroups: ChildGroupEntry[];
	}
	let { childGroups }: Props = $props();

	// Category / orbit-class names come from i18n keys (the export name is
	// English-only there); other groups keep the export name. Mirrors ChildGroups.
	function childName(c: ChildGroupEntry): string {
		const slug = c.primary_id ?? '';
		if (slug.startsWith(CATEGORY_SLUG_PREFIX)) return categoryLabel(slug);
		const className = classNameFromSlug(slug);
		return className != null ? orbitClassLabel(className) : c.name;
	}

	let tiles = $derived(childGroups.filter((c) => c.primary_id));
</script>

{#if tiles.length > 0}
	<div class="grid grid-cols-2 gap-2">
		{#each tiles as c, i (c.primary_id)}
			<GroupTile
				slug={c.primary_id ?? ''}
				name={childName(c)}
				label="{formatCompactNumber(c.n)} {m.group_stat_members()}"
				class={i === tiles.length - 1 && tiles.length % 2 === 1 ? 'col-span-2' : ''}
			/>
		{/each}
	</div>
{/if}
