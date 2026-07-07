<script lang="ts">
	import {
		CAT_ASTEROIDS,
		CAT_COMETS,
		CAT_DWARF_PLANETS,
		type SmallBodyFlagName
	} from '$lib/fetch/groups/registry';
	import { isCometClass } from '$lib/charts/orbit-zones';
	import BodyCategoryTile from './BodyCategoryTile.svelte';
	import GroupLink from './GroupLink.svelte';
	import FlagGroupLink from './FlagGroupLink.svelte';

	interface Props {
		/** SBDB orbit-class name — its `class-<NAME>` group tile. */
		orbitClass: string;
		/** NEO/PHA flag, if any. */
		flag?: SmallBodyFlagName;
	}
	let { orbitClass, flag }: Props = $props();

	// Comets bridge to the comet collection; asteroids also reach the dwarf-planet
	// collection (the largest asteroids graduate to dwarf planets).
	let comet = $derived(isCometClass(orbitClass));
</script>

<div class="grid grid-cols-2 gap-2">
	{#if comet}
		<BodyCategoryTile slug={CAT_COMETS} />
		<GroupLink className={orbitClass} />
		{#if flag}
			<FlagGroupLink {flag} class="col-span-2" />
		{/if}
	{:else}
		<BodyCategoryTile slug={CAT_ASTEROIDS} />
		<BodyCategoryTile slug={CAT_DWARF_PLANETS} />
		<GroupLink className={orbitClass} class={flag ? '' : 'col-span-2'} />
		{#if flag}
			<FlagGroupLink {flag} />
		{/if}
	{/if}
</div>
