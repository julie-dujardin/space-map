<script lang="ts">
	import { groupTypeLabel } from '$lib/format/group';
	import { categoryLabel, CAT_SOLAR_SYSTEM } from '$lib/fetch/groups/registry';
	import GroupTile from './GroupTile.svelte';
	import SolarSystemMap from '../../charts/SolarSystemMap.svelte';

	interface Props {
		/** Category slug (`cat-…`) this tile links to. */
		slug: string;
		/** Extra classes, e.g. `col-span-2` to span a 2-col grid row. */
		class?: string;
	}
	let { slug, class: className }: Props = $props();

	let name = $derived(categoryLabel(slug));
	// The Solar System tile uses the minimap diagram as its backdrop instead of
	// the group's lead image (a stray planet photo).
	let isSolarSystem = $derived(slug === CAT_SOLAR_SYSTEM);
</script>

<GroupTile
	{slug}
	{name}
	label={groupTypeLabel('category')}
	class={className}
	background={isSolarSystem ? solarSystemBg : undefined}
/>

{#snippet solarSystemBg()}
	<SolarSystemMap ariaLabel="" variant="background" />
{/snippet}
