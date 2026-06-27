<script lang="ts">
	import { groupTypeLabel } from '$lib/format/group';
	import { categoryLabel } from '$lib/fetch/groups/registry';
	import GroupTile from './GroupTile.svelte';

	interface Props {
		/** Category slug (`cat-…`) this tile links to. */
		slug: string;
		/** Extra classes, e.g. `col-span-2` to span a 2-col grid row. */
		class?: string;
	}
	let { slug, class: className }: Props = $props();

	let name = $derived(categoryLabel(slug));
</script>

<GroupTile {slug} {name} label={groupTypeLabel('category')} class={className} />
