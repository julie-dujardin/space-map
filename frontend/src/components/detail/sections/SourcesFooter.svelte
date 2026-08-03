<script lang="ts">
	import { getContext } from 'svelte';
	import ExternalLinkIcon from '@lucide/svelte/icons/external-link';
	import * as m from '$lib/paraglide/messages.js';
	import { archiveLabel, archiveRole, archiveUrl } from '$lib/credits/archive-labels';
	import { TAXONOMY_SOURCES } from '$lib/credits/taxonomy-sources';
	import type { GlobalObjectData, ModelSource } from '$lib/fetch/objects/object-data';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { applyFocus, serializeUrl, urlTypeFromId } from '$lib/state/url';

	interface Source {
		key: string;
		label: string;
		url: string;
		/** A few words on what this one contributed. Carried by the providers,
		 *  not the papers — a title and a year already say what those are. */
		note?: string;
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
		/** Ring tab: the catalogue's own tables (PDS vital statistics, the IAU
		 *  gazetteer), which the object block carries per body. */
		rings?: Source[];
	}

	let {
		global,
		earthSat = false,
		nomenclature = false,
		wikipediaLicensed = false,
		pck = false,
		sbdb = false,
		wikidata = false,
		imagery = [],
		rings = []
	}: Props = $props();

	// Per-object metadata has no per-field provenance, so we credit each source
	// from a clean signal that makes its contribution near-certain. Deduped by
	// key, so a source feeding several fields (or both orbit + SATCAT) shows once.
	let sources = $derived.by(() => {
		const out: Source[] = [];
		const seen = new Set<string>();
		const add = (key: string, label: string, url: string | null | undefined, note?: string) => {
			if (!url || seen.has(key)) return;
			seen.add(key);
			// A label that already ends in a qualifier — "NASA SPICE kernels
			// (NAIF)" — would stack a second parenthetical, so it goes bare.
			out.push({ key, label, url, note: label.endsWith(')') ? undefined : note });
		};
		// The IAU working group sets the rotational elements and radii; NAIF is
		// where we read them, so both are credited wherever either applies.
		const addPck = () => {
			add(
				'iau-wgccre',
				m.source_iau_wgccre_short(),
				'https://www.iau.org/WG100/WG100/Home.aspx',
				m.source_iau_wgccre_role()
			);
			add(
				'naif',
				m.source_spice_pck_name(),
				'https://naif.jpl.nasa.gov/naif/',
				m.source_spice_pck_role()
			);
		};

		const eph = global?.ephemeris_source;
		if (eph) add(eph, archiveLabel(eph) ?? eph, archiveUrl(eph), archiveRole(eph) ?? undefined);

		const qid = global?.cross_refs?.wikidata_qid;
		if (qid)
			add(
				'wikidata',
				m.source_wikidata_name(),
				`https://www.wikidata.org/wiki/${qid}`,
				m.source_wikidata_role()
			);
		// Lineup radius fallback (Wikidata P2120) — credit Wikidata even on a page
		// whose own group has no QID. Deduped against the QID link above by key.
		else if (wikidata)
			add(
				'wikidata',
				m.source_wikidata_name(),
				'https://www.wikidata.org/',
				m.source_wikidata_role()
			);

		// Collection-page lineup geometry/metadata, derived from the members shown.
		if (sbdb)
			add(
				'sbdb',
				m.source_sbdb_name(),
				'https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html',
				m.source_sbdb_role()
			);
		if (pck) addPck();

		const mpc = global?.cross_refs?.mpc_designation;
		if (mpc)
			add(
				'mpc',
				m.source_mpc_name(),
				`https://www.minorplanetcenter.net/db_search/show_object?utf8=%E2%9C%93&object_id=${encodeURIComponent(mpc)}`,
				m.source_mpc_role()
			);

		// Rotational elements / physical constants for planets & moons.
		if (global?.orientation) addPck();

		// Ring catalogue tables — an exact citation like the blocks below, and
		// the whole content of the Rings tab.
		for (const source of rings) add(source.url, source.label, source.url);

		// Atmospheric facts carry their own per-value citations, so these are
		// exact rather than inferred like the rest of this list.
		for (const source of global?.atmosphere?.sources ?? [])
			add(source.url, source.title, source.url);

		// Likewise the measured temperatures. Estimated ones ship no sources —
		// there is no work to credit for a number we computed here.
		for (const source of global?.temperatures?.sources ?? [])
			add(source.url, source.title, source.url);

		// The interior ships the works behind what its panel draws, so a body
		// whose composition is a spectral-class estimate credits the meteorite
		// chemistry, not a gravity field it never had.
		for (const source of global?.interior?.sources ?? []) add(source.url, source.title, source.url);

		// Where the class itself came from. Ids, not citations — see
		// `$lib/credits/taxonomy-sources`.
		for (const id of global?.interior?.taxonomy_sources ?? []) {
			const source = TAXONOMY_SOURCES[id];
			if (source) add(id, source.label(), source.url, source.role());
			else console.warn(`Missing taxonomy source: ${id}`);
		}

		// Surface-feature names come from the IAU gazetteer (hosted by USGS).
		if (nomenclature || global?.type === 'feature' || global?.has_nomenclature)
			add(
				'iau-naming',
				m.source_iau_naming_name(),
				'https://planetarynames.wr.usgs.gov/',
				m.source_iau_naming_role()
			);

		if (earthSat) {
			add(
				'celestrak',
				m.source_celestrak_name(),
				'https://celestrak.org/satcat/',
				m.source_celestrak_role()
			);
			add(
				'jonathan',
				m.source_jonathan_space_report_name(),
				'https://planet4589.org/space/',
				m.source_jonathan_space_report_role()
			);
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
			<span class="inline-flex items-center gap-1">
				<a
					href={source.url}
					target="_blank"
					rel="noopener"
					class="inline-flex items-center gap-1 underline hover:text-foreground"
					>{source.label}<ExternalLinkIcon class="size-3 shrink-0" /></a
				>
				{#if source.note}<span class="opacity-75">({source.note})</span>{/if}
			</span>
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
