<script lang="ts">
	import ExternalLinkIcon from '@lucide/svelte/icons/external-link';
	import * as m from '$lib/paraglide/messages.js';
	import { archiveLabel, archiveUrl } from '$lib/credits/archive-labels';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';

	interface Props {
		global: GlobalObjectData | null;
		/** True for earth satellites and earth-satellite group pages — credits CelesTrak SATCAT + GCAT. */
		earthSat?: boolean;
		/** Show the CC BY-SA notice when the description text is drawn from Wikipedia. */
		wikipediaLicensed?: boolean;
	}

	let { global, earthSat = false, wikipediaLicensed = false }: Props = $props();

	interface Source {
		key: string;
		label: string;
		url: string;
	}

	// Per-object metadata has no per-field provenance, so we credit each source
	// from a clean signal that makes its contribution near-certain. Deduped by
	// key, so a source feeding several fields (or both orbit + SATCAT) shows once.
	let sources = $derived.by(() => {
		const out: Source[] = [];
		const seen = new Set<string>();
		const add = (key: string, label: string, url: string | null | undefined) => {
			if (!url || seen.has(key)) return;
			seen.add(key);
			out.push({ key, label, url });
		};

		const eph = global?.ephemeris_source;
		if (eph) add(eph, archiveLabel(eph) ?? eph, archiveUrl(eph));

		const qid = global?.cross_refs?.wikidata_qid;
		if (qid) add('wikidata', m.source_wikidata_name(), `https://www.wikidata.org/wiki/${qid}`);

		const mpc = global?.cross_refs?.mpc_designation;
		if (mpc)
			add(
				'mpc',
				m.source_mpc_name(),
				`https://www.minorplanetcenter.net/db_search/show_object?utf8=%E2%9C%93&object_id=${encodeURIComponent(mpc)}`
			);

		// Rotational elements / physical constants for planets & moons.
		if (global?.orientation) {
			add('iau-wgccre', m.source_iau_wgccre_short(), 'https://www.iau.org/WG100/WG100/Home.aspx');
			add('naif', m.source_spice_pck_name(), 'https://naif.jpl.nasa.gov/naif/');
		}

		// Surface-feature names come from the IAU gazetteer (hosted by USGS).
		if (global?.type === 'feature' || global?.has_nomenclature)
			add('iau-naming', m.source_iau_naming_name(), 'https://planetarynames.wr.usgs.gov/');

		if (earthSat) {
			add('celestrak', m.source_celestrak_name(), 'https://celestrak.org/satcat/');
			add('jonathan', m.source_jonathan_space_report_name(), 'https://planet4589.org/space/');
		}

		return out;
	});
</script>

{#if wikipediaLicensed}
	<p class="text-xs text-muted-foreground">
		{m.wikipedia_license_notice()}
		<a
			href="https://creativecommons.org/licenses/by-sa/4.0/"
			target="_blank"
			rel="noopener noreferrer license"
			class="underline hover:text-foreground">CC BY-SA 4.0</a
		>.
	</p>
{/if}
{#if sources.length}
	<p class="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
		<span>{m.metadata_sources_prefix()}</span>
		{#each sources as source (source.key)}
			<a
				href={source.url}
				target="_blank"
				rel="noopener"
				class="inline-flex items-center gap-1 underline hover:text-foreground"
				>{source.label}<ExternalLinkIcon class="size-3 shrink-0" /></a
			>
		{/each}
	</p>
{/if}
