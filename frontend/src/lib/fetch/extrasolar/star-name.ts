/** The name of a star's page, for the page and for its label in the scene. */

import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { extrasolarObjectId } from './ids';
import { extrasolarLookup, systemPrimary, type ExtrasolarRecord } from './lookup';

/** The component letter at the end of a name: "HQ Tau A", "HIP 1234 Ab". */
const COMPONENT_LETTER = /\s+[A-Z][a-z]?\d?$/;

/** A star's name: the one of its object entry in the reader's language, else
 *  the one of its Metadata row. A star system with no name takes its primary's,
 *  without the component letter. */
export async function starPageName(record: ExtrasolarRecord): Promise<string> {
	const meta = record.metadata;
	const own = await fetchObjectDetail(
		extrasolarObjectId(record.id),
		meta.object,
		undefined,
		true
	).catch(() => null);
	const name = own?.localized?.name ?? meta.name;
	if (name) return name;
	const primary = systemPrimary(record);
	if (primary === null || primary === record.id) return '';
	const found = await extrasolarLookup.live(primary);
	if (found.kind !== 'live') return '';
	return (await starPageName(found.record)).replace(COMPONENT_LETTER, '');
}
