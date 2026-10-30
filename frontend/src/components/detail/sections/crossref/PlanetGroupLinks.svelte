<script lang="ts">
	import { CAT_PLANETS, CAT_SOLAR_SYSTEM, fetchGroupIndex } from '$lib/fetch/groups/registry';
	import { solarPlanetFamilyLinks, type FamilyLink } from '$lib/fetch/extrasolar/families';
	import BodyCategoryTile from './BodyCategoryTile.svelte';
	import FamilyTile from './FamilyTile.svelte';
	import SystemTile from './SystemTile.svelte';
	import type { PlanetarySystem } from '../../charts/planetary-system.svelte';

	interface Props {
		/** The planet's most specific planet families. The rarest takes the first
		 *  tile, as on an exoplanet's page. Without them the tile is Planets. */
		families?: string[];
		/** This planet's own system, when it has one to show. Takes the second
		 *  tile from the Solar System: the system is the nearer context, and the
		 *  Solar System stays one hop away on its page. */
		systemId?: string;
		system?: PlanetarySystem;
		systemName?: string;
	}
	let { families, systemId, system, systemName }: Props = $props();

	let hasSystem = $derived(!!systemId && !!system && !!systemName);

	let family = $state.raw<FamilyLink | null>(null);
	$effect(() => {
		const list = families ?? [];
		family = null;
		if (list.length === 0) return;
		let live = true;
		fetchGroupIndex().then(
			(index) => {
				if (live) family = solarPlanetFamilyLinks(list, index)[0] ?? null;
			},
			(e: unknown) => console.warn('[families] no group index:', e)
		);
		return () => {
			live = false;
		};
	});
</script>

<div class="grid grid-cols-2 gap-2">
	{#if family}
		<FamilyTile link={family} />
	{:else}
		<BodyCategoryTile slug={CAT_PLANETS} />
	{/if}
	{#if hasSystem}
		<SystemTile systemId={systemId!} system={system!} name={systemName!} />
	{:else}
		<BodyCategoryTile slug={CAT_SOLAR_SYSTEM} />
	{/if}
</div>
