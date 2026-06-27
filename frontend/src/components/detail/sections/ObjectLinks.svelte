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

	let aliases = $derived(localized?.aliases ?? []);
	let wikipediaUrl = $derived(localized?.wikipedia?.url);
	let nasaScienceUrl = $derived(global?.nasa_science_url);
	let websites = $derived(global?.wikidata?.website ?? []);
	let blogs = $derived(global?.wikidata?.blog ?? []);
	// SBDB lookup key; Wikidata and the MPC database moved to the metadata-source credits.
	let mpcDesignation = $derived(global?.cross_refs?.mpc_designation ?? global?.cross_refs?.spkid);
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
		return result;
	});
</script>

{#if links.length || designation || aliases.length}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{m.links()}</h3>
		<Separator />
		<div class="flex flex-col gap-2.5 text-sm">
			{#if designation}
				<p class="text-muted-foreground">{m.designation_label({ designation })}</p>
			{/if}
			{#if aliases.length}
				<p class="text-muted-foreground">
					{m.also_known_as({ aliases: aliases.join(', ') })}
				</p>
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
