/**
 * Who to credit for a body size read off an asteroid-moon catalogue. Shared by
 * the detail sidebar, which shows the size of one body, and the lineup footer,
 * which draws the sizes of its members.
 */
import * as m from '$lib/paraglide/messages.js';
import { archiveLabel, archiveUrl } from './archive-labels';
import { PROVIDERS } from './providers';

export interface SizeCredit {
	key: string;
	label: string;
	url?: string;
	note: string;
}

/** The catalogue behind a `radii_source`. Null for a source that is credited
 *  elsewhere: the PCK, a paper, Wikidata. `page` is the body's own catalogue
 *  entry, where the bundle has one. */
export function catalogueSizeCredit(source: string, page?: string): SizeCredit | null {
	if (source === 'johnston')
		return {
			key: 'johnston',
			label: m.source_johnston_name(),
			url: page ?? PROVIDERS.johnston.url,
			note: m.source_johnston_role()
		};
	// AsterSat is the asteroid-moon service of the NSDB.
	if (source === 'astersat')
		return {
			key: 'nsdb',
			label: archiveLabel('nsdb') ?? 'NSDB',
			url: archiveUrl('nsdb') ?? undefined,
			note: m.source_shape_role()
		};
	return null;
}
