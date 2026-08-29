<script lang="ts">
	import { CAT_MOONS } from '$lib/fetch/groups/registry';
	import BodyCategoryTile from './BodyCategoryTile.svelte';
	import BodyTile from './BodyTile.svelte';
	import SystemTile from './SystemTile.svelte';
	import type { PlanetarySystem } from '../../charts/planetary-system.svelte';

	interface Props {
		/** Host body id — its tile opens the parent's moons list. */
		parentId?: string;
		/** Host display name, when already known (moon bundles carry it). */
		parentName?: string;
		/** The system this moon belongs to. Takes the host's tile: it places the
		 *  moon among its siblings, and leads to the host's own page anyway. */
		systemId?: string;
		system?: PlanetarySystem;
		systemName?: string;
	}
	let { parentId, parentName, systemId, system, systemName }: Props = $props();

	let hasSystem = $derived(!!systemId && !!system && !!systemName);
</script>

<div class="grid grid-cols-2 gap-2">
	<BodyCategoryTile slug={CAT_MOONS} class={hasSystem || parentId ? '' : 'col-span-2'} />
	{#if hasSystem}
		<SystemTile systemId={systemId!} system={system!} name={systemName!} />
	{:else if parentId}
		<BodyTile id={parentId} name={parentName} tab="members" />
	{/if}
</div>
