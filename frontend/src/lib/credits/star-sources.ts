/**
 * The catalogues behind a star's records and a planet's: the name of each
 * source a column names, and the export's credit for each catalogue that gave
 * the values a panel shows. A credit is picked by its source page, which the
 * export writes once per catalogue. A value from the literature table cites
 * its paper, from the star's object entry.
 */

import * as m from '$lib/paraglide/messages.js';
import {
	extrasolarAllowed,
	fetchExtrasolarMetadata,
	isPaperCredit,
	isWikidataCredit,
	LITERATURE_PAGE,
	MIST_PAGE,
	type ExtrasolarCredit,
	type ExtrasolarMetadata
} from '$lib/fetch/extrasolar/files';
import { CURATED_TIER, INTERIOR_SLUG, type StarInterior } from '$lib/fetch/extrasolar/interior';
import {
	LITERATURE,
	SYSTEM_SLUG,
	astrometricOrbit,
	homeRow,
	starDistance,
	type ExtrasolarRecord,
	type StarDistance,
	type TableRow
} from '$lib/fetch/extrasolar/lookup';
import type { Planet } from '$lib/fetch/extrasolar/planets';
import type { SystemCitation, SystemNode } from '$lib/fetch/extrasolar/systems';
import type { GlobalObjectData, ValueReference } from '$lib/fetch/objects/object-data';
import {
	REFERENCE_SECTIONS,
	type Credits,
	type Reference,
	type ReferenceSection
} from './credits-payload';

const SOURCE_NAMES: Record<string, () => string> = {
	'gaia-dr3': m.source_gaia_dr3_name,
	'gaia-dr3-named': m.source_gaia_dr3_name,
	'hipparcos-2007': m.source_hipparcos_name,
	'hipparcos-1997': m.source_hipparcos_1997_name,
	'iau-wgsn': m.source_iau_wgsn_name,
	'andrae-2023': m.source_andrae_2023_name,
	'gaia-dr3-gspphot': m.source_gaia_dr3_gspphot_name,
	'gaia-dr3-gspspec': m.source_gaia_dr3_gspspec_name,
	'gaia-dr3-nss': m.source_gaia_dr3_nss_name,
	'pastel-2020': m.source_pastel_name,
	'apogee-dr17': m.source_apogee_dr17_name,
	'lamost-dr10': m.source_lamost_dr10_name,
	'gcvs-5.1': m.source_gcvs_name,
	spicy: m.source_spicy_name,
	'atnf-psrcat': m.source_atnf_name,
	xhip: m.source_xhip_name,
	simbad: m.source_simbad_name,
	'simbad-hip': m.source_simbad_name,
	'simbad-parallax': m.source_simbad_name,
	wikidata: m.source_wikidata_name,
	'reyle-2021': m.source_reyle_2021_name,
	ultracoolsheet: m.source_ultracoolsheet_name,
	'hunt-reffert-2024': m.source_hunt_reffert_2024_name,
	'magellanic-clouds': m.source_magellanic_clouds_name,
	'bailer-jones-2021': m.source_bailer_jones_2021_name,
	'rybizki-2022': m.source_rybizki_2022_name,
	'star-systems': m.source_star_systems_name,
	[LITERATURE]: m.source_literature_name,
	msc: m.source_msc_name,
	wds: m.source_wds_name,
	orb6: m.source_orb6_name,
	sbx: m.source_sbx_name,
	'el-badry-2021': m.source_el_badry_name,
	'gaia-dr3-orbits': m.source_gaia_dr3_nss_name,
	'planet-catalogues': m.source_planet_catalogues_name,
	'simbad-type': m.source_simbad_name,
	'nasa-exoplanet-archive': m.source_nasa_exoplanet_archive_name,
	'exoplanet-eu': m.source_exoplanet_eu_name,
	'open-exoplanet-catalogue': m.source_open_exoplanet_catalogue_name,
	'iau-nameexoworlds': m.source_nameexoworlds_name,
	// The inputs of an interior fit.
	'gaia-dr3-flame': m.source_gaia_dr3_flame_name,
	'gaia-dr3-flame-spec': m.source_gaia_dr3_flame_spec_name,
	'gaia-dr3-esphs': m.source_gaia_dr3_esphs_name,
	'host-star': m.source_planet_catalogues_name,
	'casagrande-2010': m.source_casagrande_2010_name,
	'flower-1996': m.source_flower_1996_name,
	radius: m.source_measured_radius_name,
	'bolometric-correction': m.source_bolometric_correction_name
};

/** The catalogue a `*_source` column or a panel row names, as a reader knows it. */
export function starSourceName(source: string): string {
	return SOURCE_NAMES[source]?.() ?? source;
}

/** What identifies each catalogue's credit, in its source page. */
export const CREDIT_PAGES = {
	gaia: '/web/gaia/dr3',
	fidelity: '/stab3588',
	orbits: '/2023A&A...674A..34G',
	xpMetallicity: '/zenodo.7945154',
	pastel: '/B/pastel',
	jmdc: '/II/345',
	simbad: '/simbad.cds.unistra.fr/',
	apogee: 'sdss4.org/dr17/',
	lamost: '/zenodo.14030249',
	lamostMStars: 'lamost.org/dr10/',
	gcvs: '//www.sai.msu.su/gcvs/',
	spicy: '/10.26131/IRSA556',
	atnf: '/research/pulsar/psrcat',
	hipparcos: '/I/311',
	hipparcosPhotometry: '/I/239',
	xhip: '/V/137D',
	reyle: '/J/A+A/650/A201',
	ultracoolsheet: '/zenodo.4169085',
	huntReffert: '/J/A+A/686/A42',
	lmc: '/s41586-019-0999-4',
	smc: '/1538-4357/abbb2b',
	bailerJones: '/1538-3881/abd806',
	nasaExoplanetArchive: '//exoplanetarchive.ipac.caltech.edu/',
	exoplanetEu: '//exoplanet.eu/',
	openExoplanetCatalogue: '/OpenExoplanetCatalogue/',
	nameExoWorlds: '//nameexoworlds.iau.org/',
	// ORB6's page is under the WDS's. The export lists the WDS first.
	wds: 'astro.gsu.edu/wds/',
	orb6: '/wds/orb6',
	msc: 'atokovin/stars/',
	sbx: '/sbx/',
	elBadry: '/zenodo.4435257',
	literature: LITERATURE_PAGE,
	starNames: '/star-names/',
	mist: MIST_PAGE,
	casagrande: '/10.1051/0004-6361/200913204',
	flower: '/10.1086/177785',
	torres: '/10.1088/0004-6256/140/5/1158'
} as const;

type CreditPage = keyof typeof CREDIT_PAGES;

/** The credit of the catalogue each `*_source` value names. A star of
 *  `magellanic-clouds` takes the paper of its cloud. */
const SOURCE_PAGES: Partial<Record<string, CreditPage>> = {
	'gaia-dr3': 'gaia',
	'gaia-dr3-named': 'gaia',
	'hipparcos-2007': 'hipparcos',
	'hipparcos-1997': 'hipparcosPhotometry',
	simbad: 'simbad',
	'simbad-hip': 'simbad',
	'simbad-parallax': 'simbad',
	'reyle-2021': 'reyle',
	ultracoolsheet: 'ultracoolsheet',
	'hunt-reffert-2024': 'huntReffert',
	'bailer-jones-2021': 'bailerJones',
	'nasa-exoplanet-archive': 'nasaExoplanetArchive',
	'exoplanet-eu': 'exoplanetEu',
	'open-exoplanet-catalogue': 'openExoplanetCatalogue',
	'iau-nameexoworlds': 'nameExoWorlds'
};

/** The credits of what a System row names as its source. */
const SYSTEM_PAGES: Partial<Record<string, CreditPage[]>> = {
	msc: ['msc'],
	wds: ['wds'],
	orb6: ['orb6'],
	sbx: ['sbx'],
	'el-badry-2021': ['elBadry'],
	simbad: ['simbad'],
	'simbad-type': ['simbad'],
	'gaia-dr3-orbits': ['orbits'],
	'open-exoplanet-catalogue': ['openExoplanetCatalogue'],
	'planet-catalogues': ['nasaExoplanetArchive', 'exoplanetEu', 'openExoplanetCatalogue']
};

/** The sources a System row names. */
function systemSources({ sources, members, orbit, star }: SystemNode): (string | null)[] {
	return [
		...sources,
		...members.map((member) => member.source),
		orbit?.massRatioSource ?? null,
		orbit?.periodSource ?? null,
		orbit?.semiMajorAxisSource ?? null,
		orbit?.eccentricitySource ?? null,
		orbit?.inclinationSource ?? null,
		orbit?.nodeSource ?? null,
		orbit?.argPeriastronSource ?? null,
		orbit?.epochSource ?? null,
		star?.massSource ?? null,
		star?.radiusSource ?? null,
		star?.teffSource ?? null,
		star?.spectralTypeSource ?? null
	];
}

/** The LMC is at 49.6 kpc and the SMC at 62.4 kpc. */
const SMC_BEYOND_PC = 56_000;

/** The credit of the distance a panel shows, where it is from a catalogue. */
function distancePage(distance: StarDistance | null): CreditPage | undefined {
	if (!distance?.source) return undefined;
	if (distance.source === 'magellanic-clouds') return distance.pc > SMC_BEYOND_PC ? 'smc' : 'lmc';
	return SOURCE_PAGES[distance.source];
}

export interface StarCredit {
	key: string;
	label: string;
	url?: string;
	note?: string;
}

/** The works of `citations`, each once, by its first citation with a title. A
 *  work with no title shows its key. */
export function citationCredits(citations: readonly SystemCitation[]): StarCredit[] {
	const works = new Map<string, StarCredit>();
	const titled = new Set<string>();
	for (const { reference, short, title, url } of citations) {
		const label = title ?? reference;
		if (label === null) continue;
		const key = url ?? label;
		if (titled.has(key) || (title === null && works.has(key))) continue;
		if (title !== null) titled.add(key);
		works.set(key, { key, label, url: url ?? undefined, note: short ?? undefined });
	}
	return [...works.values()];
}

/** The credits of the catalogues that gave this record its values and `nodes`,
 *  the System rows its panel shows, then the papers that `references` cites
 *  for its values from the literature table. `measured` is the point whose
 *  measurement the panel shows for a held star. */
export function starCredits(
	record: ExtrasolarRecord,
	references?: GlobalObjectData['references'],
	nodes: readonly SystemNode[] = [],
	measured: SystemNode | null = null
): StarCredit[] {
	const pages = new Set<CreditPage | undefined>();
	const name = record.metadata.nameSource;
	const home = homeRow(record);
	const distance = home && starDistance(home, astrometricOrbit(record));
	pages.add(distancePage(distance));
	if (name === 'iau-wgsn') pages.add('starNames');
	// A Hipparcos name is a designation from XHIP.
	else if (name === 'hipparcos-2007') pages.add('xhip');
	else if (name) pages.add(SOURCE_PAGES[name]);
	for (const source of nodes.flatMap(systemSources)) {
		for (const page of SYSTEM_PAGES[source ?? ''] ?? []) pages.add(page);
	}
	// A metallicity assumes one star, so a node shows none.
	const oneStar = !record.rows.has(SYSTEM_SLUG);
	for (const row of record.rows.values()) {
		pages.add(SOURCE_PAGES[row.text('astrometry_source') ?? '']);
		pages.add(SOURCE_PAGES[row.text('host_star_source') ?? '']);
		if (
			row.text('gaia_photometry_source') ||
			row.text('gspphot_source') ||
			row.text('gspspec_source')
		)
			pages.add('gaia');
		if (row.text('hipparcos_photometry_source')) pages.add('hipparcosPhotometry');
		if (row.text('fidelity_source')) pages.add('fidelity');
		if (row.text('orbit_source')) pages.add('gaia').add('orbits');
		if (oneStar && row.text('xgboost_source')) pages.add('xpMetallicity');
		// PASTEL, the GCVS and ATNF join by SIMBAD ids, LAMOST by its M-star catalogue.
		if (row.text('pastel_source')) pages.add('pastel').add('simbad');
		if (row.text('angular_diameter_source')) pages.add('jmdc');
		if (row.text('apogee_source')) pages.add('apogee');
		if (row.text('lamost_source')) pages.add('lamost').add('lamostMStars');
		if (row.text('gcvs_source')) pages.add('gcvs').add('simbad');
		if (row.text('spicy_source')) pages.add('spicy');
		if (row.text('atnf_source')) pages.add('atnf').add('simbad');
		if (oneStar && row.text('xhip_metallicity_source')) pages.add('xhip');
	}
	if (measured?.measuredBy === 'angular diameter') pages.add('jmdc');
	return [
		...creditsOf(pages, record.credits),
		...paperCredits([
			...(distance?.source === LITERATURE ? (references?.distance ?? []) : []),
			...(references?.paper_radius ?? []),
			...(measured?.radiusPapers ?? [])
		])
	];
}

function paperCredits(papers: readonly ValueReference[]): StarCredit[] {
	return papers.map((paper) => ({
		key: paper.url,
		label: paper.title,
		url: paper.url,
		note: paper.short
	}));
}

/** The credits of the inputs of an interior fit, by their source in the row. */
const FIT_INPUT_PAGES: Partial<Record<string, CreditPage[]>> = {
	'gaia-dr3-gspphot': ['gaia'],
	'gaia-dr3-gspspec': ['gaia'],
	'gaia-dr3-esphs': ['gaia'],
	'gaia-dr3-flame': ['gaia'],
	'gaia-dr3-flame-spec': ['gaia'],
	'apogee-dr17': ['apogee'],
	'lamost-dr10': ['lamost', 'lamostMStars'],
	'andrae-2023': ['xpMetallicity'],
	'pastel-2020': ['pastel', 'simbad'],
	xhip: ['xhip'],
	'casagrande-2010': ['casagrande'],
	// Torres 2010 corrects the coefficients of Flower's relations.
	'flower-1996': ['flower', 'torres'],
	'bolometric-correction': ['flower', 'torres']
};

/** The export takes no extinction for the B − V and V routes within this
 *  distance (pc) or up to this V, and GSP-Phot's A0 beyond. */
const SMALL_EXTINCTION_PC = 100;
const SMALL_EXTINCTION_V = 6;

/** B − V and V are Hipparcos's, else SIMBAD's. */
function photometryPage(row: TableRow, hipparcos: string): CreditPage {
	return row.number(hipparcos) !== null ? 'hipparcosPhotometry' : 'simbad';
}

/** What gave a fit's distance: a catalogue, a paper, or the parallax of the
 *  star's astrometry or of its orbit solution. */
function addDistance(
	row: TableRow,
	distance: StarDistance | null,
	pages: Set<CreditPage | undefined>,
	papers: ValueReference[],
	references: GlobalObjectData['references']
): void {
	if (distance?.source === LITERATURE) papers.push(...(references?.distance ?? []));
	else if (distance?.parallax?.fromOrbit) pages.add('gaia').add('orbits');
	else if (distance?.parallax) pages.add(SOURCE_PAGES[row.text('astrometry_source') ?? '']);
	else pages.add(distancePage(distance));
}

/** The credits of a star's interior: the papers of a curated block, or the
 *  stellar models of a fit, then the catalogues, relations and papers of its
 *  inputs. A Teff from B − V and a luminosity from V or from a measured
 *  radius rest on the photometry, distance and radius of the record. */
export function starInteriorCredits(
	interior: StarInterior,
	record: ExtrasolarRecord,
	references?: GlobalObjectData['references']
): StarCredit[] {
	if (interior.tier === CURATED_TIER) {
		return (interior.curated?.sources ?? []).map((work) => ({
			key: work.url,
			label: work.title,
			url: work.url,
			note: work.note
		}));
	}
	const { teffSource, luminositySource } = interior;
	const pages = new Set<CreditPage | undefined>();
	const papers: ValueReference[] = [];
	for (const source of [teffSource, luminositySource, interior.fehSource]) {
		for (const page of FIT_INPUT_PAGES[source ?? ''] ?? []) pages.add(page);
	}
	const home = homeRow(record);
	if (home) {
		const distance = starDistance(home, astrometricOrbit(record));
		const fromColour = teffSource === 'casagrande-2010' || teffSource === 'flower-1996';
		const fromV = luminositySource === 'bolometric-correction';
		if (teffSource === 'host-star') pages.add(SOURCE_PAGES[home.text('host_star_source') ?? '']);
		if (fromColour) pages.add(photometryPage(home, 'b_v'));
		if (fromV) {
			pages.add(photometryPage(home, 'v_mag'));
			addDistance(home, distance, pages, papers, references);
		}
		const v = home.number('v_mag') ?? home.number('simbad_v_mag');
		const reddened =
			distance !== null &&
			distance.pc > SMALL_EXTINCTION_PC &&
			(v === null || v > SMALL_EXTINCTION_V) &&
			home.number('azero_gspphot') !== null;
		if ((fromColour || fromV) && reddened) pages.add('gaia');
		if (luminositySource === 'radius') {
			if ((home.number('radius_literature') ?? 0) > 0) {
				papers.push(...(references?.paper_radius ?? []));
			} else {
				// The diameter's distance: a paper's, else the star's own parallax.
				pages.add('jmdc');
				if (home.text('distance_source') === LITERATURE) {
					papers.push(...(references?.distance ?? []));
				} else pages.add(SOURCE_PAGES[home.text('astrometry_source') ?? '']);
			}
		}
	}
	return [
		...creditsOf(new Set(['mist']), record.credits),
		...creditsOf(pages, record.credits),
		...paperCredits(papers)
	];
}

/** The credits of the catalogues that gave a planet its name and values. A
 *  sky solution from Gaia credits Gaia. */
export function planetCredits(planet: Planet, credits: readonly ExtrasolarCredit[]): StarCredit[] {
	const pages = new Set([SOURCE_PAGES[planet.name_source ?? '']]);
	for (const source of Object.values(planet.sources)) pages.add(SOURCE_PAGES[source]);
	return creditsOf(pages, credits);
}

/** The credits of the three planet catalogues, for a page about every planet. */
export function planetCatalogueCredits(credits: readonly ExtrasolarCredit[]): StarCredit[] {
	return creditsOf(
		new Set<CreditPage>(['nasaExoplanetArchive', 'exoplanetEu', 'openExoplanetCatalogue']),
		credits
	);
}

/** The export's credits of these pages, in the order of CREDIT_PAGES. */
function creditsOf(
	pages: ReadonlySet<CreditPage | undefined>,
	credits: readonly ExtrasolarCredit[]
): StarCredit[] {
	const out: StarCredit[] = [];
	for (const page of Object.keys(CREDIT_PAGES) as CreditPage[]) {
		if (!pages.has(page)) continue;
		const credit = findCredit(credits, CREDIT_PAGES[page]);
		if (credit) out.push(starCredit(credit));
	}
	return out;
}

/** A credit of the export in the reader's language. The credit of the
 *  literature table is a phrase, not a catalogue name. */
export function localizedStarCredit(credit: ExtrasolarCredit): ExtrasolarCredit {
	if (!credit.source.includes(CREDIT_PAGES.literature)) return credit;
	return {
		...credit,
		name: m.star_credit_literature_name(),
		organisation: m.star_credit_literature_note()
	};
}

function findCredit(
	credits: readonly ExtrasolarCredit[],
	page: string
): ExtrasolarCredit | undefined {
	return credits.find((credit) => credit.source.includes(page));
}

function starCredit(credit: ExtrasolarCredit): StarCredit {
	const note = credit.license ? `${credit.organisation} · ${credit.license}` : credit.organisation;
	return { key: credit.source, label: credit.name, url: credit.source, note };
}

/** The catalogues by their paper, as /credits lists its references. The credit
 *  of the literature table cites nothing itself: its papers have their rows. */
export function starPaperReferences(credits: readonly ExtrasolarCredit[]): Reference[] {
	return credits.filter(isPaperCredit).flatMap((credit) =>
		credit.citation
			? [
					{
						title: credit.citation,
						url: credit.source,
						contribution: credit.name,
						license: credit.license
					}
				]
			: []
	);
}

/** The rows of a section of the references. The star section leads with the
 *  papers of the catalogues. */
export function referenceRows(
	credits: Credits,
	section: ReferenceSection,
	starPapers: readonly Reference[]
): Reference[] {
	const rows = credits[section] ?? [];
	if (section !== 'star_references') return rows;
	const listed = new Set(starPapers.map((ref) => ref.url));
	return [...starPapers, ...rows.filter((ref) => !listed.has(ref.url))];
}

/** The number of distinct works that /credits lists as references. */
export function referenceCount(credits: Credits, stars: readonly ExtrasolarCredit[]): number {
	const papers = starPaperReferences(stars);
	const rows = REFERENCE_SECTIONS.flatMap(({ key }) => referenceRows(credits, key, papers));
	return new Set(rows.map((ref) => ref.url)).size;
}

/** The works that only the Interior table rests on. */
const INTERIOR_PAGES: readonly string[] = [
	CREDIT_PAGES.mist,
	CREDIT_PAGES.casagrande,
	CREDIT_PAGES.flower,
	CREDIT_PAGES.torres
];

/** The credits of the star catalogues for /credits; none where the host
 *  serves no extrasolar export, or may show none of it. */
export async function fetchStarCatalogueCredits(): Promise<ExtrasolarCredit[]> {
	const meta = await fetchExtrasolarMetadata().catch((e: unknown) => {
		console.warn('[credits] extrasolar metadata did not load:', e);
		return null;
	});
	return shownStarCredits(meta);
}

/** The credits of `meta` that the host may show. The works of the Interior
 *  table count only where the host may show that table. */
export function shownStarCredits(meta: ExtrasolarMetadata | null): ExtrasolarCredit[] {
	if (!meta || !Object.values(meta.tables).some((table) => extrasolarAllowed(table))) return [];
	const interior = meta.tables[INTERIOR_SLUG];
	const interiorShown = interior !== undefined && extrasolarAllowed(interior);
	return meta.credits
		.filter((c) => !isWikidataCredit(c))
		.filter((c) => interiorShown || !INTERIOR_PAGES.some((page) => c.source.includes(page)))
		.map(localizedStarCredit);
}
