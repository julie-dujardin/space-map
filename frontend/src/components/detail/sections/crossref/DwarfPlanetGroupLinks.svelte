<script lang="ts">
	import { CAT_DWARF_PLANETS } from '$lib/fetch/groups/registry';
	import BodyCategoryTile from './BodyCategoryTile.svelte';
	import GroupLink from './GroupLink.svelte';
	import SystemTile from './SystemTile.svelte';
	import type { PlanetarySystem } from '../../charts/planetary-system.svelte';

	interface Props {
		/** SBDB orbit-class name, if any; absent → the category tile spans both columns. */
		orbitClass?: string;
		/** This dwarf's own system (Pluto), which takes the orbit-class slot: the
		 *  system is the nearer context, and the zone stays one hop away. */
		systemId?: string;
		system?: PlanetarySystem;
		systemName?: string;
	}
	let { orbitClass, systemId, system, systemName }: Props = $props();

	let hasSystem = $derived(!!systemId && !!system && !!systemName);
</script>

<div class="grid grid-cols-2 gap-2">
	<BodyCategoryTile slug={CAT_DWARF_PLANETS} class={hasSystem || orbitClass ? '' : 'col-span-2'} />
	{#if hasSystem}
		<SystemTile systemId={systemId!} system={system!} name={systemName!} />
	{:else if orbitClass}
		<GroupLink className={orbitClass} />
	{/if}
</div>
