/**
 * IAU planetary nomenclature type codes — see
 * https://planetarynames.wr.usgs.gov/DescriptorTerms for the full table.
 *
 * Labels and descriptions are sourced from Wikidata at export time and
 * compiled into Paraglide messages with the keys
 * `feature_type_label_<CODE>` / `feature_type_description_<CODE>`. The four
 * IAU codes with no Wikidata entry (CL, LF, LO, ST) fall back to the
 * canonical English strings carried in the data package.
 */

import * as m from '$lib/paraglide/messages';

type MessageFn = () => string;
const messages = m as unknown as Record<string, MessageFn>;

/** Resolve an IAU 2-letter type code to a human-readable label.
 *  Falls back to the raw code when no mapping is registered. */
export function nomenclatureTypeLabel(code: string): string {
	return messages[`feature_type_label_${code}`]?.() ?? code;
}

/** Short prose description for an IAU 2-letter type code, or ``null`` when
 *  no mapping is registered. */
export function nomenclatureTypeDescription(code: string): string | null {
	return messages[`feature_type_description_${code}`]?.() ?? null;
}
