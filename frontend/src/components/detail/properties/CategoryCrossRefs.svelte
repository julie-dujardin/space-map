<script lang="ts">
	import { CAT_DWARF_PLANETS, CAT_MOONS, CAT_PLANETS } from '$lib/fetch/groups/registry';
	import BodyCategoryTile from './BodyCategoryTile.svelte';

	interface Props {
		/** The category whose page this is; its two siblings are linked. */
		slug: string;
	}
	let { slug }: Props = $props();

	// The three body-collection pages cross-link to each other so a visitor on
	// one lineup can hop to the neighbouring ones.
	const SIBLINGS: Record<string, string[]> = {
		[CAT_PLANETS]: [CAT_DWARF_PLANETS, CAT_MOONS],
		[CAT_DWARF_PLANETS]: [CAT_PLANETS, CAT_MOONS],
		[CAT_MOONS]: [CAT_PLANETS, CAT_DWARF_PLANETS]
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
