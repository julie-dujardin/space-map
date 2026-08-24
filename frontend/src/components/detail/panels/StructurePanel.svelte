<script lang="ts">
	import Structure from '../sections/Structure.svelte';
	import StructureStatCards from '../sections/StructureStatCards.svelte';
	import PropertyCategoryLinks from '../sections/crossref/PropertyCategoryLinks.svelte';
	import SourcesFooter from '../sections/SourcesFooter.svelte';
	import type { ObjectDetailData } from '$lib/fetch/objects/object-data';

	interface Props {
		data: ObjectDetailData | null;
		isBody: boolean;
	}

	let { data, isBody }: Props = $props();

	// The Structure tab's own credit: the two topic blurbs are the only licensed
	// text on it, and either one alone earns the CC BY-SA line.
	let structureProseFromWikipedia = $derived(
		!!data?.localized?.interior_page?.extract || !!data?.localized?.atmosphere_page?.extract
	);
</script>

<div class="flex flex-col gap-4">
	<!-- Above both sections rather than inside either: mass belongs to the
	     interior, pressure to the atmosphere, and the third slot to whichever
	     of the two this body has anything to say about. -->
	<StructureStatCards global={data?.global ?? null} />
	<Structure global={data?.global ?? null} localized={data?.localized ?? null} />
	<!-- Cross-refs for this subject; a group has no structure of its own, and
	     its child tiles already lead everywhere this would. -->
	{#if isBody}
		<PropertyCategoryLinks global={data?.global ?? null} />
	{/if}
	<SourcesFooter global={data?.global ?? null} wikipediaLicensed={structureProseFromWikipedia} />
</div>
