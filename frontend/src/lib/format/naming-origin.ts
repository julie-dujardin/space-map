/** Display names for IAU name-origin values.
 *
 *  The gazetteer's `ethnicity` field is free text mixing countries ("Germany"),
 *  peoples ("Greek"), languages ("Latin") and regions ("Siberia"). Its own
 *  distinctions are the data — "American" and "United States" are separate
 *  values — so each string keys its own `naming_origin_*` message rather than
 *  being folded together. Hand-authored, not generated: the values were seeded
 *  from each origin's Wikidata label, and English is the IAU string verbatim.
 *
 *  Only the top 60 origins are charted, so only those carry a key; anything
 *  else falls back to the IAU's English. */

import * as m from '$lib/paraglide/messages.js';

const messages = m as unknown as Record<string, (() => string) | undefined>;

function key(origin: string): string {
	return `naming_origin_${origin
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, '-')
		.replace(/^-|-$/g, '')}`;
}

/** Localized name for an IAU origin string, or the string itself when unmapped. */
export function namingOriginLabel(origin: string): string {
	return messages[key(origin)]?.() ?? origin;
}
