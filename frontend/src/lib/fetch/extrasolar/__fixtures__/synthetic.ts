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
	alias?: number;
	crossIds?: CrossId[];
	object?: boolean;
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
			...(objectColumn === 'object'
				? [col('object', 'bool', (r) => (r.alias ? null : (r.object ?? false)))]
				: objectColumn === 'object_file'
					? [col('object_file', 'string', () => null)]
					: []),
			col('alias_target', 'id', (r) => r.alias ?? null)
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
				{ id: SECOND },
				{ id: ALIAS, alias: STAR },
				{ id: WITH_TABLE_2, mask: 2 | 4 },
				{ id: BINARY, mask: 2 | 8, class: 'binary star' },
				{ id: SYSTEM, mask: 8, name: 'Test System', class: 'multiple star' }
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
		'system/0/0.bin.gz': encode(
			KIND_TILE,
			TOKENS.systems,
			2,
			[
				{ name: 'id', type: 'id', values: [SYSTEM, BINARY] },
				{ name: 'point', type: 'bool', values: [false, true] },
				{ name: 'members', type: 'list', values: [2, 2] },
				{ name: 'members.id', type: 'id', values: [BINARY, SECOND, null, null] },
				{ name: 'members.kind', type: 'dict', values: ['system', 'star', 'entry', 'entry'] },
				{ name: 'members.letter', type: 'string', values: ['A', 'B', 'Aa', 'Ab'] }
			],
			tileInfoBytes(0, 0, 3)
		)
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
