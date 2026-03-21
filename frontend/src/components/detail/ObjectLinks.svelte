<script lang="ts">
	import { Separator } from '$lib/components/ui/separator/index.js';
	import type { GlobalObjectData, LocalizedObjectData } from '$lib/object-data';

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
	}

	let { global, localized }: Props = $props();

	let wikipediaUrl = $derived(localized?.wikipedia?.url);
	let wikidataQid = $derived(global?.cross_refs?.wikidata_qid);
	let website = $derived(global?.wikidata?.website);
	let sbdbDesignation = $derived(
		global?.cross_refs?.sbdb_mcp_designation ?? global?.cross_refs?.sbdb_spkid
	);
	let designation = $derived(
		global?.provisional_designation ?? global?.cross_refs?.sbdb_mcp_designation
	);

	let hasLinks = $derived(wikipediaUrl || wikidataQid || website || sbdbDesignation);
</script>

{#if hasLinks || designation}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">Links</h3>
		<Separator />
		<div class="flex flex-col gap-1 text-sm">
			{#if designation}
				<p class="text-muted-foreground">Designation: {designation}</p>
			{/if}
			{#if wikipediaUrl}
				<a
					href={wikipediaUrl}
					target="_blank"
					rel="noopener noreferrer"
					class="underline hover:text-foreground text-muted-foreground">Wikipedia</a
				>
			{/if}
			{#if wikidataQid}
				<a
					href="https://www.wikidata.org/wiki/{wikidataQid}"
					target="_blank"
					rel="noopener noreferrer"
					class="underline hover:text-foreground text-muted-foreground">Wikidata ({wikidataQid})</a
				>
			{/if}
			{#if sbdbDesignation}
				<a
					href="https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html#/?sstr={encodeURIComponent(
						String(sbdbDesignation)
					)}"
					target="_blank"
					rel="noopener noreferrer"
					class="underline hover:text-foreground text-muted-foreground">JPL Small-Body Database</a
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
		</div>
	</div>
{/if}
