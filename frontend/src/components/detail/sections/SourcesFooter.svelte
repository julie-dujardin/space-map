<script lang="ts">
	import ExternalLinkIcon from '@lucide/svelte/icons/external-link';
	import * as m from '$lib/paraglide/messages.js';
	import { archiveLabel, archiveRole, archiveUrl } from '$lib/credits/archive-labels';
	import {
		orientationCredits,
		type OrientationReference,
		type OrientationSource
	} from '$lib/credits/orientation-sources';
	import { TAXONOMY_SOURCES } from '$lib/credits/taxonomy-sources';
	import type { CitedWork, GlobalObjectData } from '$lib/fetch/objects/object-data';

	interface Source {
		key: string;
		label: string;
		url: string;
		/** A few words on what this one contributed. Providers carry their own;
		 *  a cited work ships one next to its title. */
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
		/** Collection-page lineup tilts at least one member on a DAMIT lightcurve
		 *  pole rather than a PCK one → credit DAMIT for the spin. */
		lightcurvePole?: boolean;
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
		lightcurvePole = false,
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
		// A cited work keeps its note: the parenthetical its title ends in is the
		// journal, which says nothing about what this body took from the paper.
		const addWork = (work: CitedWork) => {
			if (seen.has(work.url)) return;
			seen.add(work.url);
			out.push({ key: work.url, label: work.title, url: work.url, note: work.note });
		};
		// A spin pole comes from the PCK (planets, moons, the handful of visited
		// asteroids), from DAMIT's lightcurve inversion, or — for the ringed small
		// bodies, which no kernel covers — from an occultation paper. Shared with
		// the scene's attribution popover, which credits the same elements.
		const addPole = (source: OrientationSource | undefined, reference?: OrientationReference) => {
			for (const credit of orientationCredits(source, reference))
				add(credit.key, credit.short, credit.url, credit.role);
		};
		// The lineup's radii/mass come from the same kernels as a PCK pole.
		const addPck = () => addPole(undefined);

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

		// Rotational elements. The orientation table merges three disjoint sets,
		// so the pole is credited to whichever published it — most asteroids on
		// the map spin on a DAMIT lightcurve pole the IAU never tabulated.
		const orientation = global?.orientation;
		if (orientation) addPole(orientation.source, orientation.reference);
		if (lightcurvePole) addPole('lightcurve');

		// Ring catalogue tables — an exact citation like the blocks below, and
		// the whole content of the Rings tab.
		for (const source of rings) add(source.url, source.label, source.url);

		// Atmospheric facts carry their own per-value citations, so these are
		// exact rather than inferred like the rest of this list.
		for (const source of global?.atmosphere?.sources ?? []) addWork(source);

		// Likewise the measured temperatures. Estimated ones ship no sources —
		// there is no work to credit for a number we computed here.
		for (const source of global?.temperatures?.sources ?? []) addWork(source);

		// The interior ships the works behind what its panel draws, so a body
		// whose composition is a spectral-class estimate credits the meteorite
		// chemistry, not a gravity field it never had.
		for (const source of global?.interior?.sources ?? []) addWork(source);

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
{#if orientationLabel}
	<p class="text-xs text-muted-foreground">{orientationLabel}</p>
{/if}
{#if sources.length}
	<!-- One line per credit. The title gives up its tail to the ellipsis — it is
	     in the tooltip, and this is a panel, not a bibliography — so the note,
	     which says why the work is here, always fits. -->
	<div class="text-xs/5 text-muted-foreground">
		<span>{m.metadata_sources_prefix()}</span>
		{#each sources as source (source.key)}
			<div class="flex">
				<a
					href={source.url}
					target="_blank"
					rel="noopener"
					title={source.label}
					class="truncate underline hover:text-foreground">{source.label}</a
				>
				{#if source.note}<span class="ms-1 shrink-0 opacity-75">({source.note})</span>{/if}
			</div>
		{/each}
	</div>
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
