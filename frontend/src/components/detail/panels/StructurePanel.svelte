<script lang="ts">
	import Structure from '../sections/Structure.svelte';
	import StructureStatCards from '../sections/StructureStatCards.svelte';
	import PropertyCategoryLinks from '../sections/crossref/PropertyCategoryLinks.svelte';
	import SourcesFooter from '../sections/SourcesFooter.svelte';
	import StarRowList from '../sections/star/StarRowList.svelte';
	import { starInteriorRows } from '../sections/star/interior-rows';
	import type { StarStructure } from '../state/star-interior.svelte';
	import type { ObjectDetailData } from '$lib/fetch/objects/object-data';

	interface Props {
		data: ObjectDetailData | null;
		isBody: boolean;
		/** A star other than the Sun: the interior from its Interior row. */
		star?: StarStructure | null;
	}

	let { data, isBody, star = null }: Props = $props();

	// The Structure tab's own credit: the two topic blurbs are the only licensed
	// text on it, and either one alone earns the CC BY-SA line.
	let structureProseFromWikipedia = $derived(
		!!data?.localized?.interior_page?.extract || !!data?.localized?.atmosphere_page?.extract
	);

	let starRows = $derived(star ? starInteriorRows(star.interior, star.block) : []);
	// The Sun's centre and effective temperature, K, shade a star that has no
	// reading for one end.
	const NOMINAL_PLASMA = { innerK: 15.7e6, outerK: 5772 };
</script>

{#snippet rows()}
	<StarRowList rows={starRows} />
{/snippet}

<div class="flex flex-col gap-4">
	<!-- Above both sections rather than inside either: mass belongs to the
	     interior, pressure to the atmosphere, and the third slot to whichever
	     of the two this body has anything to say about. -->
	<StructureStatCards global={data?.global ?? null} />
	{#if star}
		<Structure
			global={data?.global ?? null}
			localized={data?.localized ?? null}
			interior={star.block}
			surfaceK={star.surfaceK}
			nominalPlasma={NOMINAL_PLASMA}
			{rows}
		/>
	{:else}
		<Structure global={data?.global ?? null} localized={data?.localized ?? null} />
	{/if}
	<!-- Cross-refs for this subject; a group has no structure of its own, and
	     its child tiles already lead everywhere this would. -->
	{#if isBody}
		<PropertyCategoryLinks global={data?.global ?? null} />
	{/if}
	<SourcesFooter
		global={data?.global ?? null}
		wikipediaLicensed={structureProseFromWikipedia}
		works={star?.credits}
	/>
</div>
