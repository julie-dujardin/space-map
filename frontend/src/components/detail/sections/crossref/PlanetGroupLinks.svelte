<script lang="ts">
	import { CAT_PLANETS, CAT_SOLAR_SYSTEM } from '$lib/fetch/groups/registry';
	import BodyCategoryTile from './BodyCategoryTile.svelte';
	import SystemTile from './SystemTile.svelte';
	import type { PlanetarySystem } from '../../charts/planetary-system.svelte';

	interface Props {
		/** This planet's own system, when it has one to show. Takes the second
		 *  tile from the Solar System: the system is the nearer context, and the
		 *  Solar System stays one hop away on its page. */
		systemId?: string;
		system?: PlanetarySystem;
		systemName?: string;
	}
	let { systemId, system, systemName }: Props = $props();

	let hasSystem = $derived(!!systemId && !!system && !!systemName);
</script>

<div class="grid grid-cols-2 gap-2">
	<BodyCategoryTile slug={CAT_PLANETS} />
	{#if hasSystem}
		<SystemTile systemId={systemId!} system={system!} name={systemName!} />
	{:else}
		<BodyCategoryTile slug={CAT_SOLAR_SYSTEM} />
	{/if}
</div>
