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
	type ExtrasolarCredit
} from '$lib/fetch/extrasolar/files';
import {
	LITERATURE,
	SYSTEM_SLUG,
	astrometricOrbit,
	homeRow,
	starDistance,
	type ExtrasolarRecord,
	type StarDistance
} from '$lib/fetch/extrasolar/lookup';
import type { Planet } from '$lib/fetch/extrasolar/planets';
import type { SystemCitation, SystemNode } from '$lib/fetch/extrasolar/systems';
import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
import type { Reference } from './credits-payload';

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
	'iau-nameexoworlds': m.source_nameexoworlds_name
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
	starNames: '/star-names/'
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
	const out = creditsOf(pages, record.credits);
	const papers = [
		...(distance?.source === LITERATURE ? (references?.distance ?? []) : []),
		...(references?.paper_radius ?? []),
		...(measured?.radiusPapers ?? [])
	];
	for (const paper of papers) {
		out.push({ key: paper.url, label: paper.title, url: paper.url, note: paper.short });
	}
	return out;
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

/** The credits of the star catalogues for /credits; none where the host
 *  serves no extrasolar export, or may show none of it. */
export async function fetchStarCatalogueCredits(): Promise<ExtrasolarCredit[]> {
	const meta = await fetchExtrasolarMetadata().catch((e: unknown) => {
		console.warn('[credits] extrasolar metadata did not load:', e);
		return null;
	});
	const shown = meta && Object.values(meta.tables).some((table) => extrasolarAllowed(table));
	return shown ? meta.credits.filter((c) => !isWikidataCredit(c)).map(localizedStarCredit) : [];
}
