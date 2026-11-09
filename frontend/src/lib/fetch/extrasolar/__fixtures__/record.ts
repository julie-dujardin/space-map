/**
 * Test-only records for code that needs no lookup. A star has one Point source
 * row of the given columns, and a Binary orbit row where `orbit` gives its
 * columns. A star system node has a System row.
 */

import { Container, KIND_TILE } from '../container';
import type { ExtrasolarCredit, ExtrasolarTable } from '../files';
import { SYSTEM_SLUG, TableRow, type ExtrasolarRecord, type StarRadius } from '../lookup';
import { own } from './export';
import { encode, tileInfoBytes, type ColumnSpec } from './writer';

const SLUG = 'point-source';
const ORBIT_SLUG = 'binary-orbit';
const TOKEN = 'b'.repeat(16);

export function tableRow(slug: string, number: number, columns: ColumnSpec[]): TableRow {
	const bytes = encode(
		KIND_TILE,
		TOKEN,
		1,
		[{ name: 'id', type: 'id', values: [1] }, ...columns],
		tileInfoBytes(0, 0, number)
	);
	const table = { number, token: TOKEN, columns: [] } as unknown as ExtrasolarTable;
	return new TableRow(slug, table, new Container(own(bytes)), 0);
}

/** The columns of one row: a number is a float32, a string a dict value. */
const VALUE_TYPES = { number: 'float32', string: 'dict', boolean: 'bool' } as const;

export function valueColumns(values: Record<string, number | string | boolean>): ColumnSpec[] {
	return Object.entries(values).map(([name, value]) => ({
		name,
		type: VALUE_TYPES[typeof value as keyof typeof VALUE_TYPES],
		values: [value]
	}));
}

/** A star whose Metadata row has `radius`. */
export function pointSourceRecord(
	columns: ColumnSpec[],
	credits: ExtrasolarCredit[] = [],
	orbit?: ColumnSpec[],
	radius: StarRadius | null = null
): ExtrasolarRecord {
	const rows = new Map([[SLUG, tableRow(SLUG, 1, columns)]]);
	if (orbit) rows.set(ORBIT_SLUG, tableRow(ORBIT_SLUG, 2, orbit));
	return {
		id: 1,
		metadata: {
			id: 1,
			name: null,
			nameSource: null,
			class: 'star',
			classSource: null,
			crossIds: [],
			mask: orbit ? 6 : 2,
			system: null,
			families: 0n,
			familiesEstimated: 0n,
			spectralType: null,
			radius,
			object: false,
			aliasTarget: null
		},
		rows,
		home: SLUG,
		credits
	};
}

/** The System row of a node whose primary point is `primary`. */
export function systemRow(primary: number | null): TableRow {
	return tableRow(SYSTEM_SLUG, 3, [{ name: 'primary', type: 'id', values: [primary] }]);
}

/** A resolved star system. It has no point, so its System row is its home row. */
export function resolvedSystemRecord(id: number, primary: number | null): ExtrasolarRecord {
	return {
		id,
		metadata: {
			id,
			name: null,
			nameSource: null,
			class: 'multiple star',
			classSource: null,
			crossIds: [],
			mask: 8,
			system: null,
			families: 0n,
			familiesEstimated: 0n,
			spectralType: null,
			radius: null,
			object: false,
			aliasTarget: null
		},
		rows: new Map([[SYSTEM_SLUG, systemRow(primary)]]),
		home: SYSTEM_SLUG,
		credits: []
	};
}

/** Point source rows of the stars that the surface columns of the export
 *  (`docs/export-format/extrasolar.md`, "Surface values") tell apart, as
 *  `valueColumns` takes them. */
export const SURFACE_STARS = {
	/** A G dwarf that Gaia fits: GSP-Phot Teff and log g, FLAME's L, radius
	 *  and mass, and a V converted from G and BP − RP. */
	flame: {
		parallax: 100,
		parallax_error: 0.1,
		astrometry_source: 'gaia-dr3',
		gaia_photometry_source: 'gaia-dr3',
		gspphot_source: 'gaia-dr3',
		teff: 5600,
		teff_lower: 5550,
		teff_upper: 5650,
		teff_source: 'gaia-dr3-gspphot',
		logg: 4.4,
		logg_lower: 4.35,
		logg_upper: 4.45,
		logg_source: 'gaia-dr3-gspphot',
		luminosity: 0.75,
		luminosity_lower: 0.74,
		luminosity_upper: 0.76,
		luminosity_source: 'gaia-dr3-flame',
		radius_flame: 0.9,
		radius_flame_lower: 0.88,
		radius_flame_upper: 0.92,
		mass_flame: 0.95,
		mass_flame_lower: 0.9,
		mass_flame_upper: 1.02,
		age_flame: 4.5,
		age_flame_lower: 2,
		age_flame_upper: 8,
		evolstage_flame: 250,
		gravredshift_flame: 0.67,
		flags_flame: '00',
		apparent_v: 9.5,
		apparent_v_source: 'riello-2021',
		absolute_v: 9.5,
		extinction_source: 'negligible',
		compact: false
	},
	/** A red dwarf: GSP-Phot's Teff, its planet catalogue's log g and mass,
	 *  FLAME's radius and L, and SIMBAD's V. */
	proxima: {
		parallax: 768.07,
		parallax_error: 0.05,
		astrometry_source: 'gaia-dr3',
		host_star_source: 'nasa-exoplanet-archive',
		teff: 3000,
		teff_lower: 2990,
		teff_upper: 3010,
		teff_source: 'gaia-dr3-gspphot',
		logg: 5.2,
		logg_source: 'host-star',
		luminosity: 0.0016,
		luminosity_lower: 0.00155,
		luminosity_upper: 0.00165,
		luminosity_source: 'gaia-dr3-flame',
		radius_flame: 0.141,
		host_mass: 0.122,
		apparent_v: 11.13,
		apparent_v_source: 'simbad',
		simbad_v_mag: 11.13,
		absolute_v: 15.56,
		extinction_source: 'negligible',
		compact: false
	},
	/** A star that Gaia saturates on: a Teff from Hipparcos's B − V, L from a
	 *  paper's radius, and no log g. */
	tauCeti: {
		parallax: 273.8,
		parallax_error: 0.17,
		astrometry_source: 'hipparcos-2007',
		hipparcos_photometry_source: 'hipparcos-2007',
		v_mag: 3.49,
		b_v: 0.727,
		radius_literature: 0.793,
		teff: 5344,
		teff_source: 'casagrande-2010',
		luminosity: 0.46,
		luminosity_source: 'radius',
		apparent_v: 3.49,
		apparent_v_source: 'hipparcos-2007',
		absolute_v: 5.68,
		extinction_source: 'negligible',
		compact: false
	},
	/** A giant: a Teff from SIMBAD's B − V, L from its V through a bolometric
	 *  correction, a JMDC diameter, and no log g. */
	arcturus: {
		parallax: 88.83,
		parallax_error: 0.54,
		astrometry_source: 'hipparcos-2007',
		simbad_photometry_source: 'simbad',
		simbad_b_mag: 1.18,
		simbad_v_mag: -0.05,
		angular_diameter: 21.0,
		angular_diameter_source: 'jmdc',
		teff: 4286,
		teff_source: 'flower-1996',
		luminosity: 170,
		luminosity_source: 'bolometric-correction',
		apparent_v: -0.05,
		apparent_v_source: 'simbad',
		absolute_v: -0.31,
		extinction_source: 'negligible',
		compact: false
	},
	/** A white dwarf with a paper's Teff, log g, mass and radius (Sirius B),
	 *  and Gaia's fits of it as a main-sequence star. */
	whiteDwarf: {
		parallax: 379.2,
		parallax_error: 1.6,
		astrometry_source: 'gaia-dr3',
		gspphot_source: 'gaia-dr3',
		teff_gspphot: 9800,
		radius_gspphot: 1.6,
		radius_flame: 1.7,
		radius_flame_lower: 1.65,
		radius_flame_upper: 1.75,
		mass_flame: 2.1,
		mass_flame_lower: 2.0,
		mass_flame_upper: 2.2,
		age_flame: 0.4,
		age_flame_lower: 0.3,
		age_flame_upper: 0.5,
		evolstage_flame: 300,
		gravredshift_flame: 0.8,
		flags_flame: '00',
		teff_literature: 25369,
		teff_literature_error: 46,
		logg_literature: 8.591,
		logg_literature_error: 0.016,
		mass_literature: 1.018,
		mass_literature_lower: 1.007,
		mass_literature_upper: 1.029,
		radius_literature: 0.008098,
		teff: 25369,
		teff_lower: 25323,
		teff_upper: 25415,
		teff_source: 'literature',
		logg: 8.591,
		logg_lower: 8.575,
		logg_upper: 8.607,
		logg_source: 'literature',
		luminosity: 0.0245,
		luminosity_source: 'radius',
		apparent_v: 8.44,
		apparent_v_source: 'simbad',
		absolute_v: 11.33,
		extinction_source: 'negligible',
		compact: true
	},
	/** A white dwarf of a paper's sample: L from its mass and log g, and no
	 *  radius but Gaia's main-sequence fits. */
	sampleWhiteDwarf: {
		parallax: 40,
		parallax_error: 0.05,
		astrometry_source: 'gaia-dr3',
		gspphot_source: 'gaia-dr3',
		radius_gspphot: 0.4,
		radius_flame: 0.45,
		mass_flame: 0.5,
		age_flame: 9,
		evolstage_flame: 200,
		flags_flame: '00',
		teff_literature: 6000,
		teff_literature_error: 60,
		logg_literature: 8.0,
		logg_literature_error: 0.02,
		mass_literature: 0.6,
		mass_literature_lower: 0.59,
		mass_literature_upper: 0.61,
		teff: 6000,
		teff_lower: 5940,
		teff_upper: 6060,
		teff_source: 'literature',
		logg: 8.0,
		logg_lower: 7.98,
		logg_upper: 8.02,
		logg_source: 'literature',
		luminosity: 0.00025,
		luminosity_source: 'mass-gravity',
		apparent_v: 16.2,
		apparent_v_source: 'riello-2021',
		absolute_v: 14.21,
		extinction_source: 'negligible',
		compact: true
	},
	/** A pulsar, a compact star: a mass from its planet catalogue, and nothing
	 *  of its surface. */
	pulsar: {
		parallax: 1.0,
		parallax_error: 0.1,
		host_star_source: 'nasa-exoplanet-archive',
		host_mass: 1.4,
		compact: true
	},
	/** The point of two stars: only its V and absolute V, and Gaia's flag. */
	twoStars: {
		parallax: 50,
		parallax_error: 0.1,
		astrometry_source: 'gaia-dr3',
		gaia_photometry_source: 'gaia-dr3',
		phot_variable_flag: 'VARIABLE',
		apparent_v: 7.2,
		apparent_v_source: 'riello-2021',
		absolute_v: 5.69,
		extinction_source: 'negligible'
	},
	/** A far star with no extinction known: its absolute V takes none. */
	farStar: {
		parallax: 2,
		parallax_error: 0.05,
		astrometry_source: 'gaia-dr3',
		gaia_photometry_source: 'gaia-dr3',
		apparent_v: 12.4,
		apparent_v_source: 'riello-2021',
		absolute_v: 3.91,
		extinction_source: 'unknown',
		compact: false
	}
} satisfies Record<string, Record<string, number | string | boolean>>;
