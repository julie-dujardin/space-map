<script lang="ts">
	import ExternalLinkIcon from '@lucide/svelte/icons/external-link';
	import { Separator } from '$lib/components/ui/separator/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData, LocalizedObjectData } from '$lib/fetch/objects/object-data';

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
	}

	let { global, localized }: Props = $props();

	let wikipediaUrl = $derived(localized?.wikipedia?.url);
	let nasaScienceUrl = $derived(global?.nasa_science_url);
	let wikidataQid = $derived(global?.cross_refs?.wikidata_qid);
	let websites = $derived(global?.wikidata?.website ?? []);
	let blogs = $derived(global?.wikidata?.blog ?? []);
	let mpcDesignation = $derived(global?.cross_refs?.mpc_designation ?? global?.cross_refs?.spkid);
	let mpcDesignationOnly = $derived(global?.cross_refs?.mpc_designation);
	let naifId = $derived(global?.cross_refs?.naif_id);
	let noradCatId = $derived(global?.cross_refs?.norad_cat_id);
	let designation = $derived(
		global?.provisional_designation ?? global?.cross_refs?.mpc_designation
	);

	interface Link {
		href: string;
		label: string;
	}

	let links = $derived.by(() => {
		const result: Link[] = [];
		if (wikipediaUrl) result.push({ href: wikipediaUrl, label: m.wikipedia() });
		if (nasaScienceUrl) result.push({ href: nasaScienceUrl, label: m.nasa_science() });
		for (const url of websites)
			result.push({ href: url, label: new URL(url).hostname.replace(/^www\./, '') });
		for (const url of blogs) result.push({ href: url, label: m.property_name_blog() });
		if (naifId)
			result.push({
				href: `https://ssd.jpl.nasa.gov/api/horizons.api?format=text&COMMAND='${naifId}'`,
				label: m.jpl_horizons({ id: String(naifId) })
			});
		if (mpcDesignation)
			result.push({
				href: `https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html#/?sstr=${encodeURIComponent(String(mpcDesignation))}`,
				label: m.jpl_sbdb({ id: String(mpcDesignation) })
			});
		if (mpcDesignationOnly)
			result.push({
				href: `https://www.minorplanetcenter.net/db_search/show_object?utf8=%E2%9C%93&object_id=${encodeURIComponent(String(mpcDesignationOnly))}`,
				label: m.mpc_database({ id: String(mpcDesignationOnly) })
			});
		if (noradCatId) {
			result.push({
				href: `https://celestrak.org/NORAD/elements/graph-orbit-data.php?CATNR=${noradCatId}`,
				label: m.celestrak_orbit_data({ id: String(noradCatId) })
			});
			result.push({
				href: `https://www.n2yo.com/satellite/?s=${noradCatId}`,
				label: m.n2yo_satellite_tracker({ id: String(noradCatId) })
			});
		}
		if (wikidataQid)
			result.push({
				href: `https://www.wikidata.org/wiki/${wikidataQid}`,
				label: m.wikidata_label({ qid: wikidataQid })
			});
		return result;
	});
</script>

{#if links.length || designation}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{m.links()}</h3>
		<Separator />
		<div class="flex flex-col gap-2.5 text-sm">
			{#if designation}
				<p class="text-muted-foreground">{m.designation_label({ designation })}</p>
			{/if}
			{#each links as link (link.href)}
				<a
					href={link.href}
					target="_blank"
					rel="noopener"
					class="w-fit inline-flex items-center gap-1 underline hover:text-foreground text-muted-foreground"
					>{link.label}<ExternalLinkIcon class="size-3 shrink-0" /></a
				>
			{/each}
		</div>
	</div>
{/if}
