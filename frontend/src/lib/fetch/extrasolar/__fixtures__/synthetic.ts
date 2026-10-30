/**
 * Test-only synthetic extrasolar export: Metadata, table 1 (Point source),
 * table 2 (Binary orbit) and table 3 (System), each one level-0 tile, written
 * with the test writer.
 */

import { Container, KIND_SPLIT, KIND_TILE, type CrossId } from '../container';
import type { ExtrasolarMetadata, ExtrasolarTable } from '../files';
import { TableRow } from '../lookup';
import { encode, tileInfoBytes, type ColumnSpec } from './writer';
import { valueColumns } from './record';

/** In level-0 pixel 0, the one tile of each table. */
export const CELL = 123_456;
export const idOf = (serial: number, table: number, cell = CELL) =>
	serial * 2 ** 29 + table * 2 ** 24 + cell;
export const STAR = idOf(0, 1);
export const SECOND = idOf(1, 1);
export const ALIAS = idOf(900, 1);
export const RETIRED = idOf(2, 1);
export const WITH_TABLE_2 = idOf(3, 1);
/** A point that holds two stars, in the resolved system SYSTEM with SECOND. */
export const BINARY = idOf(4, 1);
export const SYSTEM = idOf(0, 3);
/** A held star inside BINARY. */
export const HELD = idOf(1, 3);

export const TOKENS = {
	metadata: 'a'.repeat(16),
	points: 'b'.repeat(16),
	orbits: 'c'.repeat(16),
	systems: 'd'.repeat(16)
};

/** Bits 6 and 57 of a Gaia DR3 `flags`, past the range of a double. */
export const ORBIT_FLAGS = (1n << 57n) | (1n << 6n);

function table(
	slug: string,
	number: number | null,
	token: string,
	distribution?: string
): ExtrasolarTable {
	return {
		number,
		token,
		split: `${slug}/split.bin.gz`,
		tile: `${slug}/{level}/{pixel}.bin.gz`,
		max_rows: 10,
		rows: 0,
		tiles: 12,
		columns: [],
		distribution
	};
}

/** Every pixel a leaf: the tile of a cell is its level-0 pixel. */
function split(token: string): Uint8Array {
	return encode(KIND_SPLIT, token, 12, [
		{ name: 'split', type: 'bits', values: new Array(12).fill(false) }
	]);
}

interface MetaRow {
	id: number;
	name?: string;
	class?: string;
	mask?: number;
	system?: number;
	alias?: number;
	crossIds?: CrossId[];
	object?: boolean;
	spectralType?: string;
}

/** The column of the Metadata tile that says whether an ID has an object
 *  entry: `object`, the `object_file` of deployed exports, or none. */
export type ObjectColumn = 'object' | 'object_file' | 'none';

function metadataTile(
	token: string,
	rows: MetaRow[],
	objectColumn: ObjectColumn = 'object'
): Uint8Array {
	const sorted = [...rows].sort((a, b) => a.id - b.id);
	const col = (
		name: string,
		type: ColumnSpec['type'],
		f: (r: MetaRow) => ColumnSpec['values'][number]
	): ColumnSpec => ({ name, type, values: sorted.map(f) });
	return encode(
		KIND_TILE,
		token,
		sorted.length,
		[
			col('id', 'id', (r) => r.id),
			col('name', 'string', (r) => (r.alias ? null : (r.name ?? `Star ${r.id}`))),
			col('name_source', 'dict', (r) => (r.alias ? null : 'gaia-dr3')),
			col('class', 'dict', (r) => (r.alias ? null : (r.class ?? 'star'))),
			col('class_source', 'dict', (r) => (r.alias ? null : 'gaia-dr3')),
			col('cross_ids', 'cross_ids', (r) => (r.alias ? null : (r.crossIds ?? []))),
			col('mask', 'uint32', (r) => r.mask ?? (r.alias ? 0 : 2)),
			col('system', 'id', (r) => r.system ?? null),
			...(objectColumn === 'object'
				? [col('object', 'bool', (r) => (r.alias ? null : (r.object ?? false)))]
				: objectColumn === 'object_file'
					? [col('object_file', 'string', () => null)]
					: []),
			col('alias_target', 'id', (r) => r.alias ?? null),
			col('spectral_type', 'string', (r) => r.spectralType ?? null)
		],
		tileInfoBytes(0, 0, 0)
	);
}

function dataTile(
	token: string,
	number: number,
	rows: { id: number; parallax: number }[],
	more: ColumnSpec[] = []
): Uint8Array {
	return encode(
		KIND_TILE,
		token,
		rows.length,
		[
			{ name: 'id', type: 'id', values: rows.map((r) => r.id) },
			{ name: 'parallax', type: 'float32', values: rows.map((r) => r.parallax) },
			{ name: 'parallax_error', type: 'float32', values: rows.map(() => 0.1) },
			...more
		],
		tileInfoBytes(0, 0, number)
	);
}

/** The rows SYSTEM, HELD and BINARY. A value list follows the rows, or the
 *  items of the list before it. */
function systemTile(): Uint8Array {
	const column = (name: string, type: ColumnSpec['type'], values: ColumnSpec['values']) => ({
		name,
		type,
		values
	});
	return encode(
		KIND_TILE,
		TOKENS.systems,
		3,
		[
			column('id', 'id', [SYSTEM, HELD, BINARY]),
			column('point', 'bool', [false, false, true]),
			column('depth', 'int16', [0, 2, 1]),
			column('stars', 'int32', [3, 1, 2]),
			column('ra', 'float64', [45, 45, 45]),
			column('dec', 'float64', [30, 30, 30]),
			column('label', 'string', ['AB', 'Aa', null]),
			column('spectral_type', 'string', ['G2V+K1V', null, null]),
			column('evidence', 'dict', [null, null, 'gaia-dr3-orbit']),
			column('sources', 'list', [2, 0, 1]),
			column('sources.item', 'dict', ['msc', 'wds', 'gaia-dr3-orbits']),
			column('tree_source', 'dict', ['star-systems', 'star-systems', 'star-systems']),
			column('parent', 'id', [null, BINARY, SYSTEM]),
			column('root', 'id', [SYSTEM, SYSTEM, SYSTEM]),
			column('primary', 'id', [BINARY, null, BINARY]),
			column('distance', 'float64', [100, 100, 100]),
			column('members', 'list', [2, 0, 2]),
			column('members.id', 'id', [BINARY, SECOND, HELD, null]),
			column('members.kind', 'dict', ['system', 'star', 'held star', 'entry']),
			column('members.letter', 'dict', ['A', 'B', 'Aa', 'Ab']),
			column('members.inner', 'string', [null, null, null, 'b']),
			column('members.label', 'string', [null, 'Second', null, null]),
			column('members.source', 'dict', ['msc', 'msc', 'msc', 'gaia-dr3-orbits']),
			column('members.spectral_type', 'string', ['G2V', 'K1V', null, null]),
			column('members.v_mag', 'float32', [1.5, null, null, null]),
			column('members.g_mag', 'float32', [null, 2.5, null, null]),
			column('members.mass', 'float32', [null, 0.5, null, 0.25]),
			column('members.separation', 'float64', [null, 17.5, null, null]),
			column('members.position_angle', 'float32', [null, 90, null, null]),
			column('members.period', 'float64', [null, 29000, 40, 40]),
			column('members.eccentricity', 'float32', [null, 0.5, null, null]),
			column('members.semi_major_axis', 'float32', [null, 17.5, null, null]),
			column('members.known', 'list', [0, 2, 1, 0]),
			column('members.known.item', 'dict', ['visual', 'visual orbit', 'spectroscopic']),
			column('members.ids', 'cross_ids', [
				[],
				[],
				[],
				[{ catalogue: 'gaia', release: 'dr3', catalogueId: '43' }]
			]),
			column('tree', 'list', [3, null, null]),
			column('tree.id', 'id', [SYSTEM, HELD, BINARY]),
			column('tree.parent', 'id', [null, BINARY, SYSTEM]),
			column('tree.point', 'bool', [false, false, true]),
			column('tree.stars', 'int32', [3, 1, 2]),
			column('tree.class', 'dict', ['multiple star', 'star', 'binary star']),
			column('tree.label', 'string', ['AB', 'Aa', null]),
			column('orbit', 'list', [1, null, null]),
			column('orbit.a', 'float64', [23.5]),
			column('orbit.e', 'float64', [0.5]),
			column('orbit.i', 'float64', [80]),
			column('orbit.om', 'float64', [200]),
			column('orbit.w', 'float64', [230]),
			column('orbit.ma', 'float64', [10]),
			column('orbit.n', 'float64', [0.01]),
			column('orbit.epoch', 'float64', [2451545]),
			column('orbit.phase', 'dict', ['periastron']),
			column('orbit.period', 'float64', [29000]),
			column('orbit.semi_major_axis', 'float64', [23.5]),
			column('orbit.semi_major_axis_arcsec', 'float64', [null]),
			column('orbit.eccentricity', 'float64', [0.5]),
			column('orbit.inclination', 'float64', [79]),
			column('orbit.node', 'float64', [205]),
			column('orbit.node_ascending', 'bool', [false]),
			column('orbit.arg_periastron', 'float64', [231]),
			column('orbit.periastron_time', 'float64', [2435000]),
			column('orbit.barycentre', 'float64', [0.45]),
			column('orbit.centre', 'dict', ['barycentre']),
			column('orbit.mass_ratio_source', 'dict', ['literature']),
			column('orbit.period_source', 'dict', ['orb6']),
			column('orbit.semi_major_axis_source', 'dict', ['gaia-dr3-orbits']),
			column('orbit.eccentricity_source', 'dict', ['orb6']),
			column('orbit.inclination_source', 'dict', ['orb6']),
			column('orbit.node_source', 'dict', [null]),
			column('orbit.arg_periastron_source', 'dict', ['orb6']),
			column('orbit.epoch_source', 'dict', ['orb6']),
			column('orbit.assumed', 'list', [1]),
			column('orbit.assumed.item', 'dict', ['node']),
			column('orbit.computed', 'list', [1]),
			column('orbit.computed.item', 'dict', ['semi_major_axis']),
			column('orbit.references', 'list', [2]),
			column('orbit.references.source', 'dict', ['orb6', 'literature']),
			column('orbit.references.reference', 'string', ['Msn2023', 'doyle2011']),
			column('orbit.references.short', 'dict', [null, 'Doyle et al. 2011']),
			column('orbit.references.title', 'dict', [null, 'A title']),
			column('orbit.references.url', 'dict', [null, 'https://example.org/']),
			column('star', 'list', [null, 1, null]),
			column('star.mass', 'float32', [0.5]),
			column('star.mass_source', 'dict', ['literature']),
			column('star.radius', 'float32', [null]),
			column('star.radius_source', 'dict', [null]),
			column('star.teff', 'float32', [4500]),
			column('star.teff_source', 'dict', ['open-exoplanet-catalogue']),
			column('star.spectral_type', 'string', ['K1V']),
			column('star.spectral_type_source', 'dict', ['msc']),
			column('star.references', 'list', [1]),
			column('star.references.source', 'dict', ['literature']),
			column('star.references.reference', 'string', ['doyle2011']),
			column('star.references.short', 'dict', ['Doyle et al. 2011']),
			column('star.references.title', 'dict', ['A title']),
			column('star.references.url', 'dict', ['https://example.org/'])
		],
		tileInfoBytes(0, 0, 3)
	);
}

export interface SyntheticExport {
	meta: ExtrasolarMetadata;
	/** Decoded payloads by path under `v1/x/`. */
	payloads: Record<string, Uint8Array>;
}

export function syntheticExport(
	options: { metaDistribution?: string; objectColumn?: ObjectColumn } = {}
): SyntheticExport {
	const meta: ExtrasolarMetadata = {
		format: 1,
		exported: '',
		registry: { ingest: 1, host: 'test' },
		tables: {
			metadata: table('metadata', null, TOKENS.metadata, options.metaDistribution),
			'point-source': table('point-source', 1, TOKENS.points),
			'binary-orbit': table('binary-orbit', 2, TOKENS.orbits, 'site-only'),
			system: table('system', 3, TOKENS.systems)
		},
		trees: {},
		credits: [{ name: 'Test catalogue', organisation: 'Test', source: 'https://example.org/' }]
	};
	const payloads: Record<string, Uint8Array> = {
		'metadata/split.bin.gz': split(TOKENS.metadata),
		'point-source/split.bin.gz': split(TOKENS.points),
		'binary-orbit/split.bin.gz': split(TOKENS.orbits),
		'system/split.bin.gz': split(TOKENS.systems),
		'metadata/0/0.bin.gz': metadataTile(
			TOKENS.metadata,
			[
				{
					id: STAR,
					name: 'Test Star',
					crossIds: [
						{ catalogue: 'gaia', release: 'dr3', catalogueId: '42' },
						{ catalogue: 'wikidata', release: 'qid', catalogueId: 'Q86' }
					],
					object: true
				},
				{ id: SECOND, system: SYSTEM },
				{ id: ALIAS, alias: STAR },
				{ id: WITH_TABLE_2, mask: 2 | 4 },
				{ id: BINARY, mask: 2 | 8, class: 'binary star', system: SYSTEM },
				{ id: SYSTEM, mask: 8, name: 'Test System', class: 'multiple star' },
				{ id: HELD, mask: 8, name: 'Test System Aa', system: SYSTEM }
			],
			options.objectColumn
		),
		'point-source/0/0.bin.gz': dataTile(TOKENS.points, 1, [
			{ id: STAR, parallax: 379.21 },
			{ id: SECOND, parallax: 0.3 },
			{ id: WITH_TABLE_2, parallax: 2 },
			{ id: BINARY, parallax: 10 }
		]),
		'binary-orbit/0/0.bin.gz': dataTile(
			TOKENS.orbits,
			2,
			[{ id: WITH_TABLE_2, parallax: 7 }],
			[
				{ name: 'nss_solution_type', type: 'dict', values: ['Orbital'] },
				{ name: 'flags', type: 'uint64', values: [ORBIT_FLAGS] },
				{ name: 'corr_vec', type: 'float32_list', values: [[0.5, NaN, -0.25]] }
			]
		),
		'system/0/0.bin.gz': systemTile()
	};
	return { meta, payloads };
}

/** One Point source row of STAR. A number is a float32 column, a string a dict column. */
export function pointSourceRow(values: Record<string, number | string>): TableRow {
	const columns: ColumnSpec[] = [
		{ name: 'id', type: 'id', values: [STAR] },
		...valueColumns(values)
	];
	const bytes = encode(KIND_TILE, TOKENS.points, 1, columns, tileInfoBytes(0, 0, 1));
	const tile = new Container(bytes.buffer as ArrayBuffer);
	return new TableRow('point-source', table('point-source', 1, TOKENS.points), tile, 0);
}
