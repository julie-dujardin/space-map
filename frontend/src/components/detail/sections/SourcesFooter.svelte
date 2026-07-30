<script lang="ts">
	import { getContext } from 'svelte';
	import ExternalLinkIcon from '@lucide/svelte/icons/external-link';
	import * as m from '$lib/paraglide/messages.js';
	import { archiveLabel, archiveUrl } from '$lib/credits/archive-labels';
	import type { GlobalObjectData, ModelSource } from '$lib/fetch/objects/object-data';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { applyFocus, serializeUrl, urlTypeFromId } from '$lib/state/url';

	interface Source {
		key: string;
		label: string;
		url: string;
	}

	interface Props {
		global: GlobalObjectData | null;
		/** True for earth satellites and earth-satellite group pages — credits CelesTrak SATCAT + GCAT. */
		earthSat?: boolean;
		/** True for feature-type group pages — their whole content is the IAU gazetteer. */
		nomenclature?: boolean;
		/** Show the CC BY-SA notice when the description text is drawn from Wikipedia. */
		wikipediaLicensed?: boolean;
		/** Collection-page lineup draws radii/pole/mass from SPICE PCK → credit IAU WGCCRE + NAIF. */
		pck?: boolean;
		/** Collection-page lineup draws diameter/albedo/spectral type from the Small-Body Database. */
		sbdb?: boolean;
		/** Collection-page lineup uses the Wikidata radius fallback for some bodies' size. */
		wikidata?: boolean;
		/** Distinct surface-imagery credits for the lineup spheres (deduped by author). */
		imagery?: Source[];
	}

	let {
		global,
		earthSat = false,
		nomenclature = false,
		wikipediaLicensed = false,
		pck = false,
		sbdb = false,
		wikidata = false,
		imagery = []
	}: Props = $props();

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
		// Lineup radius fallback (Wikidata P2120) — credit Wikidata even on a page
		// whose own group has no QID. Deduped against the QID link above by key.
		else if (wikidata) add('wikidata', m.source_wikidata_name(), 'https://www.wikidata.org/');

		// Collection-page lineup geometry/metadata, derived from the members shown.
		if (sbdb) add('sbdb', m.source_sbdb_name(), 'https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html');
		if (pck) {
			add('iau-wgccre', m.source_iau_wgccre_short(), 'https://www.iau.org/WG100/WG100/Home.aspx');
			add('naif', m.source_spice_pck_name(), 'https://naif.jpl.nasa.gov/naif/');
		}

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

		// Atmospheric facts carry their own per-value citations, so these are
		// exact rather than inferred like the rest of this list.
		for (const source of global?.atmosphere?.sources ?? [])
			add(source.url, source.title, source.url);

		// Surface-feature names come from the IAU gazetteer (hosted by USGS).
		if (nomenclature || global?.type === 'feature' || global?.has_nomenclature)
			add('iau-naming', m.source_iau_naming_name(), 'https://planetarynames.wr.usgs.gov/');

		if (earthSat) {
			add('celestrak', m.source_celestrak_name(), 'https://celestrak.org/satcat/');
			add('jonathan', m.source_jonathan_space_report_name(), 'https://planet4589.org/space/');
		}

		return out;
	});

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	function provenanceLabel(p: ModelSource['provenance']): string {
		if (p === 'radar') return m.model_provenance_radar();
		if (p === 'lightcurve') return m.model_provenance_lightcurve();
		return m.model_provenance_missions();
	}

	let modelSource = $derived(global?.model_source);

	// Deep-link to the observing spacecraft's page; the mesh isn't worth flying to.
	let missionHref = $derived.by(() => {
		const mission = modelSource?.mission;
		if (!mission || !appState) return undefined;
		return serializeUrl(
			applyFocus(appState.view, {
				type: urlTypeFromId(mission.primary_id),
				id: mission.primary_id,
				name: mission.name
			})
		);
	});

	function openMission(e: MouseEvent) {
		const mission = modelSource?.mission;
		if (!mission || !focusObject) return;
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		e.preventDefault();
		focusObject(mission.primary_id, mission.name, { moveCamera: false });
	}

	// CK-refit stream, or the estimated two-vector/nadir pointing fallback.
	let orientationLabel = $derived(
		global?.attitude
			? m.attitude_source_spice_ck()
			: global?.pointing
				? m.attitude_source_estimated()
				: null
	);
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
{#if modelSource}
	<p class="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
		<span>{provenanceLabel(modelSource.provenance)}</span>
		{#if modelSource.mission}
			<a href={missionHref} onclick={openMission} class="underline hover:text-foreground"
				>{modelSource.mission.name}</a
			>
		{/if}
		{#if modelSource.archive}
			{#if modelSource.archive_url}
				<a
					href={modelSource.archive_url}
					target="_blank"
					rel="noopener"
					class="inline-flex items-center gap-1 underline hover:text-foreground"
					>{modelSource.archive}<ExternalLinkIcon class="size-3 shrink-0" /></a
				>
			{:else}
				<span>{modelSource.archive}</span>
			{/if}
		{/if}
	</p>
{/if}
{#if orientationLabel}
	<p class="text-xs text-muted-foreground">{orientationLabel}</p>
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
{#if imagery.length}
	<p class="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
		<span>{m.attribution_imagery()}:</span>
		{#each imagery as source (source.key)}
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
