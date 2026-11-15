/**
 * Test-only galaxy: the Redshift row and the object entry of the Milky Way as
 * the export writes them (`docs/export-format/extrasolar.md`, "Redshift
 * (table 4)"; `docs/export-format/objects.md`), a record of them, and a
 * synthetic export that holds the galaxy alone.
 */

import { KIND_TILE } from '../container';
import type { ExtrasolarMetadata } from '../files';
import { REDSHIFT_SLUG, type ExtrasolarRecord } from '../lookup';
import type { GalaxyFact, GlobalObjectData, ValueReference } from '$lib/fetch/objects/object-data';
import { tableRow } from './record';
import { idOf, metadataTile, split, table, type SyntheticExport } from './synthetic';
import { encode, tileInfoBytes, type ColumnSpec } from './writer';

export const GALAXY = idOf(0, 4);

const TOKENS = { metadata: 'a'.repeat(16), redshift: 'e'.repeat(16) };
const SOURCE = 'galaxy-literature';

const float64 = (name: string, value: number): ColumnSpec => ({
	name,
	type: 'float64',
	values: [value]
});
const float32 = (name: string, value: number): ColumnSpec => ({
	name,
	type: 'float32',
	values: [value]
});
const dict = (name: string, value: string): ColumnSpec => ({ name, type: 'dict', values: [value] });

function bounded(name: string, value: number, lower: number, upper: number): ColumnSpec[] {
	return [
		float32(name, value),
		float32(`${name}_lower`, lower),
		float32(`${name}_upper`, upper),
		dict(`${name}_source`, SOURCE)
	];
}

/** The columns of the Milky Way's Redshift row, without its `id`. */
export const MILKY_WAY_COLUMNS: ColumnSpec[] = [
	float64('ra', 266.4168076),
	float64('dec', -29.007839),
	dict('position_source', SOURCE),
	float64('distance', 8277),
	float64('distance_lower', 8243),
	float64('distance_upper', 8311),
	dict('distance_method', 'dynamical'),
	dict('distance_source', SOURCE),
	dict('morphological_type', 'SAB(rs)bc'),
	dict('morphology_source', SOURCE),
	...bounded('stellar_mass', 5.04e10, 4.52e10, 5.47e10),
	...bounded('total_mass', 1.08e12, 0.94e12, 1.28e12),
	...bounded('star_formation_rate', 1.65, 1.46, 1.84)
];

const work = (short: string): ValueReference => ({
	short,
	title: `Title of ${short}`,
	url: `https://doi.org/${encodeURIComponent(short)}`
});

const fact = (values: Omit<GalaxyFact, 'references'>, ...shorts: string[]): GalaxyFact => ({
	...values,
	references: shorts.map(work)
});

const GRAVITY = ['GRAVITY Collaboration 2022', 'GRAVITY Collaboration 2021'];
const COUNT_INPUTS = ['Cautun et al. 2020', 'Chabrier 2003'];

/** The `references` and `facts` of the Milky Way's object entry. */
export const MILKY_WAY_ENTRY: Pick<GlobalObjectData, 'references' | 'facts'> = {
	references: {
		position: [work('Xu et al. 2022')],
		distance: GRAVITY.map(work),
		morphology: [work('de Vaucouleurs & Pence 1978')],
		stellar_mass: [work('Cautun et al. 2020')],
		total_mass: [work('Cautun et al. 2020')],
		star_formation_rate: [work('Licquia & Newman 2015')]
	},
	facts: {
		black_hole_mass: fact({ value: 4297000, lower: 4285000, upper: 4309000 }, GRAVITY[0]),
		age: fact({ value: 13 }, 'Xiang & Rix 2022'),
		scale_length: fact({ value: 2640, lower: 2510, upper: 2770 }, 'Licquia & Newman 2016'),
		thin_disc_scale_height: fact({ value: 300, lower: 240, upper: 360 }, 'Jurić et al. 2008'),
		thick_disc_scale_height: fact({ value: 900, lower: 720, upper: 1080 }, 'Jurić et al. 2008'),
		half_light_radius: fact({ value: 5750, lower: 5370, upper: 6130 }, 'Lian et al. 2024'),
		disc_radius: fact({ lower: 26000 }, 'López-Corredoira et al. 2018'),
		bar_half_length: fact(
			{ value: 5000, lower: 4800, upper: 5200 },
			'Wegg, Gerhard & Portail 2015'
		),
		stellar_halo_mass: fact(
			{ value: 1.4e9, lower: 1e9, upper: 1.8e9 },
			'Deason, Belokurov & Sanders 2019'
		),
		circular_speed: fact({ value: 236, lower: 229, upper: 243 }, 'Reid et al. 2019'),
		supernova_rate: fact(
			{ value: 1.63, lower: 1.17, upper: 2.09 },
			'Rozwadowska, Vissani & Cappellaro 2021'
		),
		globular_clusters: fact({ value: 157 }, 'Harris 2010'),
		satellite_galaxies: fact({ lower: 65 }, 'Pace 2025'),
		planets_per_star: fact({ value: 1.6, lower: 0.71, upper: 2.32 }, 'Cassan et al. 2012'),
		free_floating_planets_per_star: fact({ value: 21, lower: 8, upper: 44 }, 'Sumi et al. 2023'),
		star_count: fact({ lower: 1e11, upper: 2e11, estimate: true }, ...COUNT_INPUTS),
		planet_count: fact(
			{ lower: 8e10, upper: 5e11, estimate: true },
			...COUNT_INPUTS,
			'Cassan et al. 2012'
		),
		orbital_period: fact({ value: 212, lower: 202, upper: 223, estimate: true }, 'Reid et al. 2019')
	}
};

/** A galaxy whose Redshift row has `columns`. */
export function galaxyRecord(columns: ColumnSpec[] = MILKY_WAY_COLUMNS): ExtrasolarRecord {
	return {
		id: GALAXY,
		metadata: {
			id: GALAXY,
			name: 'Milky Way',
			nameSource: SOURCE,
			class: 'galaxy',
			classSource: SOURCE,
			crossIds: [
				{ catalogue: 'galaxy', release: 'key', catalogueId: 'milky-way' },
				{ catalogue: 'wikidata', release: 'qid', catalogueId: 'Q321' }
			],
			mask: 16,
			system: null,
			families: 0n,
			familiesEstimated: 0n,
			spectralType: null,
			radius: null,
			object: true,
			aliasTarget: null
		},
		rows: new Map([[REDSHIFT_SLUG, tableRow(REDSHIFT_SLUG, 4, columns)]]),
		home: REDSHIFT_SLUG,
		credits: []
	};
}

/** The kinds of `about-data.json` that the page of the Sun's galaxy counts. */
export const ABOUT_KINDS = [
	{ id: 'galaxy', count: 1 },
	{ id: 'star', count: 180_622_691 },
	{ id: 'star_system', count: 1_689_592 },
	{ id: 'planet', count: 7_538 }
];

/** An export that holds the galaxy alone, and names it as the galaxy of the Sun. */
export function galaxyExport(): SyntheticExport {
	const meta: ExtrasolarMetadata = {
		format: 1,
		exported: '',
		registry: { ingest: 1, host: 'test' },
		tables: {
			metadata: table('metadata', null, TOKENS.metadata),
			[REDSHIFT_SLUG]: table(REDSHIFT_SLUG, 4, TOKENS.redshift)
		},
		trees: {},
		credits: [],
		home_galaxy: GALAXY
	};
	const redshift = encode(
		KIND_TILE,
		TOKENS.redshift,
		1,
		[{ name: 'id', type: 'id', values: [GALAXY] }, ...MILKY_WAY_COLUMNS],
		tileInfoBytes(0, 0, 4)
	);
	return {
		meta,
		payloads: {
			'metadata/split.bin.gz': split(TOKENS.metadata),
			'redshift/split.bin.gz': split(TOKENS.redshift),
			'metadata/0/0.bin.gz': metadataTile(TOKENS.metadata, [
				{
					id: GALAXY,
					name: 'Milky Way',
					class: 'galaxy',
					mask: 16,
					object: true,
					crossIds: [{ catalogue: 'galaxy', release: 'key', catalogueId: 'milky-way' }]
				}
			]),
			'redshift/0/0.bin.gz': redshift
		}
	};
}
