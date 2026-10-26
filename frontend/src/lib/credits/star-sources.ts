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
	type ExtrasolarCredit
} from '$lib/fetch/extrasolar/files';
import {
	LITERATURE,
	astrometricOrbit,
	homeRow,
	starDistance,
	type ExtrasolarRecord,
	type StarDistance
} from '$lib/fetch/extrasolar/lookup';
import type { Planet } from '$lib/fetch/extrasolar/planets';
import type { GlobalObjectData } from '$lib/fetch/objects/object-data';

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
	[LITERATURE]: m.source_literature_name,
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
	simbad: '/simbad.cds.unistra.fr/',
	apogee: 'sdss4.org/dr17/',
	lamost: '/zenodo.14030249',
	lamostMStars: 'lamost.org/dr10/',
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
	literature: '/constants/stars/literature.py',
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
	url: string;
	note?: string;
}

/** The credits of the catalogues that gave this record its values, then the
 *  papers that `references` cites for its values from the literature table. */
export function starCredits(
	record: ExtrasolarRecord,
	references?: GlobalObjectData['references']
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
		if (row.text('xgboost_source')) pages.add('xpMetallicity');
		// These rows join by ids from SIMBAD and from the LAMOST M-star catalogue.
		if (row.text('pastel_source')) pages.add('pastel').add('simbad');
		if (row.text('apogee_source')) pages.add('apogee');
		if (row.text('lamost_source')) pages.add('lamost').add('lamostMStars');
		if (row.text('xhip_metallicity_source')) pages.add('xhip');
	}
	const out = creditsOf(pages, record.credits);
	const papers = distance?.source === LITERATURE ? (references?.distance ?? []) : [];
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

/** The credits of the star catalogues for /credits; none where the host
 *  serves no extrasolar export, or may show none of it. */
export async function fetchStarCatalogueCredits(): Promise<ExtrasolarCredit[]> {
	const meta = await fetchExtrasolarMetadata().catch((e: unknown) => {
		console.warn('[credits] extrasolar metadata did not load:', e);
		return null;
	});
	const shown = meta && Object.values(meta.tables).some((table) => extrasolarAllowed(table));
	return shown ? meta.credits.map(localizedStarCredit) : [];
}
