/** Display strings for IAU surface-feature types.
 *
 *  One name per type, keyed by the readable slug stem of its `ft-` page
 *  (`feature_type_label_crater`) — generated per locale by
 *  `data/.../export/localization.py` from the type's Wikidata entity, with the
 *  in-repo IAU constants backfilling the four codes that have no entity. */

import * as m from '$lib/paraglide/messages.js';
import { FEATURE_TYPE_SLUG_PREFIX } from '$lib/fetch/groups/registry';

// Generated keys, looked up dynamically.
const messages = m as unknown as Record<string, (() => string) | undefined>;

/** Localized type name for an `ft-` slug; `undefined` before the slug resolves. */
export function featureTypeLabel(slug: string | undefined): string | undefined {
	if (!slug) return undefined;
	return messages[`feature_type_label_${stem(slug)}`]?.();
}

/** The IAU descriptor definition ("A circular depression"), when one exists. */
export function featureTypeDescription(slug: string | undefined): string | undefined {
	if (!slug) return undefined;
	return messages[`feature_type_description_${stem(slug)}`]?.();
}

function stem(slug: string): string {
	return slug.startsWith(FEATURE_TYPE_SLUG_PREFIX)
		? slug.slice(FEATURE_TYPE_SLUG_PREFIX.length)
		: slug;
}
