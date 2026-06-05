/**
 * IAU planetary nomenclature type codes — see
 * https://planetarynames.wr.usgs.gov/DescriptorTerms for the full table.
 *
 * Labels and descriptions mirror ``data/constants/feature_types.py`` (which
 * sources its descriptions from each KMZ's ``edomvd`` metadata). Inline
 * English for now; if/when these get user-facing in more places we'll move
 * them through Paraglide.
 */

export interface NomenclatureType {
	label: string;
	description: string;
}

export const NOMENCLATURE_TYPES: Record<string, NomenclatureType> = {
	AA: { label: 'Crater', description: 'A circular depression' },
	AL: {
		label: 'Albedo feature',
		description: 'Geographic area distinguished by amount of reflected light'
	},
	AR: { label: 'Arcus', description: 'Arc-shaped feature' },
	CA: { label: 'Catena', description: 'Chain of craters' },
	CB: {
		label: 'Cavus',
		description: 'Hollows, irregular steep-sided depressions usually in arrays or clusters'
	},
	CH: { label: 'Chaos', description: 'Distinctive area of broken terrain' },
	CL: {
		label: 'Collum',
		description: '“Neck”; the region connecting two lobes of a bilobed asteroid'
	},
	CM: { label: 'Chasma', description: 'A deep, elongated, steep-sided depression' },
	CO: { label: 'Collis', description: 'Small hills or knobs' },
	CR: { label: 'Corona', description: 'Ovoid-shaped feature' },
	DO: { label: 'Dorsum', description: 'Ridge' },
	ER: { label: 'Eruptive centre', description: 'Active volcanic centers on Io' },
	FA: { label: 'Facula', description: 'Bright spot' },
	FE: { label: 'Flexus', description: 'A very low curvilinear ridge with a scalloped pattern' },
	FL: { label: 'Fluctus', description: 'Flow terrain' },
	FM: { label: 'Flumen', description: 'Channel on Titan that might carry liquid' },
	FO: { label: 'Fossa', description: 'Long, narrow depression' },
	FR: { label: 'Farrum', description: 'Pancake-like structure, or a row of such structures' },
	FT: {
		label: 'Fretum',
		description: 'Strait, a narrow passage of liquid connecting two larger areas of liquid'
	},
	IN: {
		label: 'Insula',
		description:
			'Island (islands), an isolated land area (or group of such areas) surrounded by, or nearly surrounded by, a liquid area (sea or lake).'
	},
	LA: { label: 'Labes', description: 'Landslide' },
	LB: { label: 'Labyrinthus', description: 'Complex of intersecting valleys or ridges.' },
	LC: {
		label: 'Lacus',
		description:
			'“Lake” or small plain; on Titan, a “lake” or small, dark plain with discrete, sharp boundaries'
	},
	LF: {
		label: 'Astronaut-named feature',
		description: 'Lunar features at or near Apollo landing sites'
	},
	LG: { label: 'Large ringed feature', description: 'Cryptic ringed features' },
	LI: {
		label: 'Linea',
		description: 'A dark or bright elongate marking, may be curved or straight'
	},
	LN: {
		label: 'Lingula',
		description: 'Extension of plateau having rounded lobate or tongue-like boundaries'
	},
	LO: { label: 'Lobus', description: 'One of two lobes of a contact binary asteroid' },
	LU: {
		label: 'Lacuna',
		description: 'Irregularly shaped depression on Titan having the appearance of a dry lake bed'
	},
	MA: { label: 'Macula', description: 'Dark spot, may be irregular' },
	ME: {
		label: 'Mare',
		description:
			'“Sea”; large circular plain; on Titan, large expanses of dark materials thought to be liquid hydrocarbons'
	},
	MN: { label: 'Mensa', description: 'A flat-topped prominence with cliff-like edges' },
	MO: { label: 'Mons', description: 'Mountain' },
	OC: { label: 'Oceanus', description: 'A very large dark area on the moon' },
	PA: { label: 'Palus', description: '“Swamp”; small plain' },
	PE: {
		label: 'Patera',
		description: 'An irregular crater, or a complex one with scalloped edges'
	},
	PL: { label: 'Planitia', description: 'Low plain' },
	PM: { label: 'Planum', description: 'Plateau or high plain' },
	PR: { label: 'Promontorium', description: '“Cape”; headland promontoria' },
	PU: { label: 'Plume', description: 'Cryo-volcanic features on Triton' },
	RE: {
		label: 'Regio',
		description:
			'A large area marked by reflectivity or color distinctions from adjacent areas, or a broad geographic region'
	},
	RI: { label: 'Rima', description: 'Fissure' },
	RU: { label: 'Rupes', description: 'Scarp' },
	SA: { label: 'Saxum', description: 'Boulder or rock' },
	SC: { label: 'Scopulus', description: 'Lobate or irregular scarp' },
	SE: {
		label: 'Serpens',
		description: 'Sinuous feature with segments of positive and negative relief along its length'
	},
	SF: {
		label: 'Satellite feature',
		description:
			'A feature that shares the name of an associated feature. For example, on the Moon the craters referred to as “Lettered Craters” are classified in the gazetteer as “Satellite Features.”'
	},
	SI: { label: 'Sinus', description: '“Bay”; small plain' },
	ST: { label: 'Statio', description: 'Spacecraft landing site' },
	SU: { label: 'Sulcus', description: 'Subparallel furrows and ridges' },
	TA: { label: 'Terra', description: 'Extensive land mass' },
	TE: { label: 'Tessera', description: 'Tile-like, polygonal terrain' },
	TH: { label: 'Tholus', description: 'Small domical mountain or hill' },
	UN: { label: 'Unda', description: 'Dunes' },
	VA: { label: 'Vallis', description: 'Valley' },
	VI: { label: 'Virga', description: 'A streak or stripe of color' },
	VS: { label: 'Vastitas', description: 'Extensive plain' }
};

/** Resolve an IAU 2-letter type code to a human-readable label.
 *  Falls back to the raw code when no mapping is registered. */
export function nomenclatureTypeLabel(code: string): string {
	return NOMENCLATURE_TYPES[code]?.label ?? code;
}

/** Short prose description for an IAU 2-letter type code, or ``null`` when
 *  no mapping is registered. */
export function nomenclatureTypeDescription(code: string): string | null {
	return NOMENCLATURE_TYPES[code]?.description ?? null;
}
