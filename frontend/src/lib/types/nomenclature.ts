/**
 * IAU planetary nomenclature type codes — see
 * https://planetarynames.wr.usgs.gov/DescriptorTerms for the full table.
 *
 * Inline English for now; if/when these get user-facing in more places we'll
 * move them through Paraglide. Only the subset that the surface-feature
 * renderer actually draws is included — non-circular types
 * (catenae, lineae, valles, …) are filtered out before reaching this map.
 */

export const NOMENCLATURE_TYPE_LABELS: Record<string, string> = {
	AA: 'Albedo feature',
	AL: 'Albedo feature',
	AR: 'Arcus',
	AS: 'Astrum',
	CB: 'Cavus',
	CL: 'Collis',
	CR: 'Crater',
	DC: 'Dome',
	ER: 'Eruptive centre',
	FA: 'Farrum',
	FR: 'Flexus',
	FT: 'Fluctus',
	IN: 'Insula',
	LA: 'Labes',
	LB: 'Labyrinthus',
	LC: 'Lacuna',
	LU: 'Lacus',
	LG: 'Landing site',
	ME: 'Mare',
	MN: 'Mensa',
	MO: 'Mons',
	OC: 'Oceanus',
	PA: 'Palus',
	PE: 'Patera',
	PL: 'Planitia',
	PM: 'Planum',
	PU: 'Plume',
	PR: 'Promontorium',
	RE: 'Regio',
	RA: 'Reticulum',
	SA: 'Satellite feature',
	SF: 'Salt feature',
	SI: 'Sinus',
	SU: 'Sulcus',
	TA: 'Terra',
	TH: 'Tholus',
	UN: 'Unda',
	VS: 'Vastitas',
	VI: 'Virga'
};

/** Resolve an IAU 2-letter type code to a human-readable label.
 *  Falls back to the raw code when no mapping is registered. */
export function nomenclatureTypeLabel(code: string): string {
	return NOMENCLATURE_TYPE_LABELS[code] ?? code;
}
