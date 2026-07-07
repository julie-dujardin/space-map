<script lang="ts">
	import { CAT_MOONS } from '$lib/fetch/groups/registry';
	import BodyCategoryTile from './BodyCategoryTile.svelte';
	import BodyTile from './BodyTile.svelte';

	interface Props {
		/** Host body id — its tile opens the parent's moons list. */
		parentId?: string;
		/** Host display name, when already known (moon bundles carry it). */
		parentName?: string;
	}
	let { parentId, parentName }: Props = $props();
</script>

<div class="grid grid-cols-2 gap-2">
	<BodyCategoryTile slug={CAT_MOONS} class={parentId ? '' : 'col-span-2'} />
	{#if parentId}
		<BodyTile id={parentId} name={parentName} tab="members" />
	{/if}
</div>
