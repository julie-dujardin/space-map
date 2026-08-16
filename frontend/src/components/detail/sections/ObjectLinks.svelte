<script lang="ts">
	import ExternalLinkIcon from '@lucide/svelte/icons/external-link';
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData, LocalizedObjectData } from '$lib/fetch/objects/object-data';
	import Row from './kit/Row.svelte';

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

	// Catalogue IDs read as links too — each is this object's key in someone
	// else's dataset. The export's own key, a probe's synthetic id, and the
	// duplicate `sbdb_primary_designation` are left out. Name-like designations
	// first, then catalogue numbers in issuer order.
	let identifiers = $derived.by(() => {
		const x = global?.cross_refs;
		const out: Array<{ label: string; value: string }> = [];
		if (x?.mpc_designation) out.push({ label: m.id_mpc(), value: String(x.mpc_designation) });
		if (global?.provisional_designation)
			out.push({ label: m.id_provisional(), value: global.provisional_designation });
		if (x?.naif_id != null) out.push({ label: m.id_naif(), value: String(x.naif_id) });
		if (x?.spkid != null) out.push({ label: m.id_spk(), value: String(x.spkid) });
		if (x?.norad_cat_id != null) out.push({ label: m.id_norad(), value: String(x.norad_cat_id) });
		if (x?.cospar_id) out.push({ label: m.id_cospar(), value: x.cospar_id });
		if (x?.wikidata_qid) out.push({ label: m.id_wikidata(), value: x.wikidata_qid });
		return out;
	});

	interface Link {
		href: string;
		label: string;
	}

	let links = $derived.by(() => {
		const result: Link[] = [];
		if (wikipediaUrl) result.push({ href: wikipediaUrl, label: m.source_wikipedia_name() });
		if (nasaScienceUrl) result.push({ href: nasaScienceUrl, label: m.nasa_science() });
		for (const url of websites)
			result.push({ href: url, label: new URL(url).hostname.replace(/^www\./, '') });
		for (const url of blogs) result.push({ href: url, label: m.property_name_blog() });
		if (naifId)
			result.push({
				href: `https://ssd.jpl.nasa.gov/api/horizons.api?format=text&COMMAND='${naifId}'`,
				label: m.jpl_horizons()
			});
		if (mpcDesignation)
			result.push({
				href: `https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html#/?sstr=${encodeURIComponent(String(mpcDesignation))}`,
				label: m.jpl_sbdb()
			});
		if (noradCatId) {
			result.push({
				href: `https://celestrak.org/NORAD/elements/graph-orbit-data.php?CATNR=${noradCatId}`,
				label: m.celestrak_orbit_data()
			});
			result.push({
				href: `https://www.n2yo.com/satellite/?s=${noradCatId}`,
				label: m.n2yo_satellite_tracker()
			});
		}
		return result;
	});
</script>

{#if links.length || aliases.length || identifiers.length}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{m.links()}</h3>
		<div class="border-border/60 border-t"></div>
		<div class="flex flex-col gap-2.5 text-sm">
			{#if identifiers.length}
				<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2.5">
					{#each identifiers as id (id.label)}
						<Row label={id.label}>
							<span class="tabular-nums select-all">{id.value}</span>
						</Row>
					{/each}
				</dl>
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
