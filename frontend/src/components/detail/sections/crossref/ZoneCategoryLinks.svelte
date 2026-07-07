<script lang="ts">
	import { CAT_ASTEROIDS, CAT_COMETS, CAT_DWARF_PLANETS } from '$lib/fetch/groups/registry';
	import { isCometClass } from '$lib/charts/orbit-zones';
	import BodyCategoryTile from './BodyCategoryTile.svelte';

	interface Props {
		/** Small-body orbit-class name of the focused zone (e.g. "MBA", "JFC"). */
		className: string;
	}
	let { className }: Props = $props();

	let comet = $derived(isCometClass(className));
</script>

<div class="grid grid-cols-2 gap-2">
	{#if comet}
		<BodyCategoryTile slug={CAT_COMETS} class="col-span-2" />
	{:else}
		<BodyCategoryTile slug={CAT_ASTEROIDS} />
		<BodyCategoryTile slug={CAT_DWARF_PLANETS} />
	{/if}
</div>
