<script lang="ts">
	import { Separator } from '$lib/components/ui/separator/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData, LocalizedObjectData } from '$lib/fetch/objects/object-data';

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
	}

	let { global, localized }: Props = $props();

	let wikipediaUrl = $derived(localized?.wikipedia?.url);
	let wikidataQid = $derived(global?.cross_refs?.wikidata_qid);
	let website = $derived(global?.wikidata?.website?.[0]);
	let sbdbDesignation = $derived(
		global?.cross_refs?.sbdb_mcp_designation ?? global?.cross_refs?.sbdb_spkid
	);
	let horizonsNaifId = $derived(global?.cross_refs?.horizons_naif_id);
	let noradCatId = $derived(global?.cross_refs?.celestrak_norad_cat_id);
	let designation = $derived(
		global?.provisional_designation ?? global?.cross_refs?.sbdb_mcp_designation
	);

	let hasLinks = $derived(
		wikipediaUrl || wikidataQid || website || sbdbDesignation || horizonsNaifId || noradCatId
	);
</script>

{#if hasLinks || designation}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{m.links()}</h3>
		<Separator />
		<div class="flex flex-col gap-1 text-sm">
			{#if designation}
				<p class="text-muted-foreground">{m.designation_label({ designation })}</p>
			{/if}
			{#if wikipediaUrl}
				<a
					href={wikipediaUrl}
					target="_blank"
					rel="noopener noreferrer"
					class="underline hover:text-foreground text-muted-foreground">{m.wikipedia()}</a
				>
			{/if}
			{#if website}
				<a
					href={website}
					target="_blank"
					rel="noopener noreferrer"
					class="underline hover:text-foreground text-muted-foreground">{website}</a
				>
			{/if}
			{#if horizonsNaifId}
				<a
					href="https://ssd.jpl.nasa.gov/api/horizons.api?format=text&COMMAND='{horizonsNaifId}'"
					target="_blank"
					rel="noopener noreferrer"
					class="underline hover:text-foreground text-muted-foreground"
					>{m.jpl_horizons({ id: String(horizonsNaifId) })}</a
				>
			{/if}
			{#if sbdbDesignation}
				<a
					href="https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html#/?sstr={encodeURIComponent(
						String(sbdbDesignation)
					)}"
					target="_blank"
					rel="noopener noreferrer"
					class="underline hover:text-foreground text-muted-foreground"
					>{m.jpl_sbdb({ id: String(sbdbDesignation) })}</a
				>
			{/if}
			{#if noradCatId}
				<a
					href="https://www.n2yo.com/satellite/?s={noradCatId}"
					target="_blank"
					rel="noopener noreferrer"
					class="underline hover:text-foreground text-muted-foreground"
					>{m.n2yo_satellite_tracker({ id: String(noradCatId) })}</a
				>
			{/if}
			{#if wikidataQid}
				<a
					href="https://www.wikidata.org/wiki/{wikidataQid}"
					target="_blank"
					rel="noopener noreferrer"
					class="underline hover:text-foreground text-muted-foreground"
					>{m.wikidata_label({ qid: wikidataQid })}</a
				>
			{/if}
		</div>
	</div>
{/if}
