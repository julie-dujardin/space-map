/**
 * The catalogues behind a star's records: the name of each source a table
 * column names, and the export's credit for each catalogue that gave the
 * values a panel shows. A credit is picked by its source page, which the
 * export writes once per catalogue.
 */

import * as m from '$lib/paraglide/messages.js';
import {
	extrasolarAllowed,
	fetchExtrasolarMetadata,
	type ExtrasolarCredit
} from '$lib/fetch/extrasolar/files';
import type { ExtrasolarRecord } from '$lib/fetch/extrasolar/lookup';

const SOURCE_NAMES: Record<string, () => string> = {
	'gaia-dr3': m.source_gaia_dr3_name,
	'hipparcos-2007': m.source_hipparcos_name,
	'iau-wgsn': m.source_iau_wgsn_name,
	wikidata: m.source_wikidata_name
};

/** The catalogue a `*_source` column names, as a reader knows it. */
export function starSourceName(source: string): string {
	return SOURCE_NAMES[source]?.() ?? source;
}

/** What identifies each catalogue's credit, in its source page. */
export const CREDIT_PAGES = {
	gaia: '/web/gaia/dr3',
	fidelity: '/stab3588',
	hipparcos: '/I/311',
	hipparcosPhotometry: '/I/239',
	xhip: '/V/137D',
	starNames: '/star-names/'
} as const;

type CreditPage = keyof typeof CREDIT_PAGES;

export interface StarCredit {
	key: string;
	label: string;
	url: string;
	note?: string;
}

/** The credits of the catalogues that gave this record its values. */
export function starCredits(record: ExtrasolarRecord): StarCredit[] {
	const pages = new Set<CreditPage>();
	const meta = record.metadata;
	if (meta.nameSource === 'iau-wgsn') pages.add('starNames');
	// A Hipparcos name is a designation from XHIP.
	if (meta.nameSource === 'hipparcos-2007') pages.add('xhip');
	for (const row of record.rows.values()) {
		if (row.text('astrometry_source') === 'gaia-dr3') pages.add('gaia');
		if (row.text('astrometry_source') === 'hipparcos-2007') pages.add('hipparcos');
		if (row.text('gaia_photometry_source') || row.text('gspphot_source')) pages.add('gaia');
		if (row.text('hipparcos_photometry_source')) pages.add('hipparcosPhotometry');
		if (row.text('fidelity_source')) pages.add('fidelity');
	}
	const out: StarCredit[] = [];
	for (const page of Object.keys(CREDIT_PAGES) as CreditPage[]) {
		if (!pages.has(page)) continue;
		const credit = findCredit(record.credits, CREDIT_PAGES[page]);
		if (credit) out.push(starCredit(credit));
	}
	return out;
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
	return shown ? meta.credits : [];
}
