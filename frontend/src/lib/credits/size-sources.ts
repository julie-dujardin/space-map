/**
 * Who to credit for a body value read off a catalogue. Shared by the detail
 * sidebar, which shows the size and the mass of one body, the lineup footer,
 * which draws the sizes of its members, and the mass chart.
 */
import * as m from '$lib/paraglide/messages.js';
import { archiveLabel, archiveUrl } from './archive-labels';
import { PROVIDERS, type ProviderKey } from './providers';

export interface SizeCredit {
	key: string;
	label: string;
	url?: string;
	note: string;
	/** A paper: the footer keeps its note as for any cited work. */
	paper?: true;
}

/** A catalogue source of a body value, by the export's `*_source` name. */
export type CatalogueSource =
	| 'jpl_satellite_physical'
	| 'sbdb'
	| 'ssodnet'
	| 'johnston'
	| 'wikidata'
	| 'astersat';

// The keys of the panel's other credits, so a catalogue that gave two values
// shows once.
const PROVIDER_KEYS: Record<Exclude<CatalogueSource, 'astersat'>, ProviderKey> = {
	jpl_satellite_physical: 'jpl-satellite-physical',
	sbdb: 'sbdb',
	ssodnet: 'ssodnet',
	johnston: 'johnston',
	wikidata: 'wikidata'
};

/** The credit of a catalogue for what `note` names. `page` is the body's own
 *  Johnston entry, where the bundle has one. */
export function catalogueCredit(source: CatalogueSource, note: string, page?: string): SizeCredit {
	// AsterSat is the asteroid-moon service of the NSDB.
	if (source === 'astersat')
		return {
			key: 'nsdb',
			label: archiveLabel('nsdb') ?? 'NSDB',
			url: archiveUrl('nsdb') ?? undefined,
			note
		};
	const key = PROVIDER_KEYS[source];
	const provider = PROVIDERS[key];
	const url = source === 'johnston' && page ? page : provider.url;
	return { key, label: provider.name(), url, note };
}

/** The catalogue behind a `radii_source`. Null for a source that is credited
 *  elsewhere: the PCK, a paper, Wikidata. */
export function catalogueSizeCredit(source: string, page?: string): SizeCredit | null {
	if (source === 'johnston') return catalogueCredit(source, m.source_johnston_role(), page);
	if (source === 'ssodnet' || source === 'astersat')
		return catalogueCredit(source, m.source_shape_role());
	return null;
}
