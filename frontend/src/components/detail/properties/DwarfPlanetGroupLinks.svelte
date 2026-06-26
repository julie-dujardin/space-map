<script lang="ts">
	import { CAT_DWARF_PLANETS } from '$lib/fetch/groups/registry';
	import BodyCategoryTile from './BodyCategoryTile.svelte';
	import GroupLink from './GroupLink.svelte';

	interface Props {
		/** SBDB orbit-class name, if any; absent → the category tile spans both columns. */
		orbitClass?: string;
	}
	let { orbitClass }: Props = $props();
</script>

<div class="grid grid-cols-2 gap-2">
	<BodyCategoryTile slug={CAT_DWARF_PLANETS} class={orbitClass ? '' : 'col-span-2'} />
	{#if orbitClass}
		<GroupLink className={orbitClass} />
	{/if}
</div>
