/**
 * Test-only synthetic extrasolar export: Metadata, table 1 (Point source) and
 * table 2, each one level-0 tile, written with the test writer.
 */

import { KIND_SPLIT, KIND_TILE, type CrossId } from '../container';
import type { ExtrasolarMetadata, ExtrasolarTable } from '../files';
import { encode, tileInfoBytes, type ColumnSpec } from './writer';

/** In level-0 pixel 0, the one tile of each table. */
export const CELL = 123_456;
export const idOf = (serial: number, table: number, cell = CELL) =>
	serial * 2 ** 29 + table * 2 ** 24 + cell;
export const STAR = idOf(0, 1);
export const SECOND = idOf(1, 1);
export const ALIAS = idOf(900, 1);
export const RETIRED = idOf(2, 1);
export const WITH_TABLE_2 = idOf(3, 1);

export const TOKENS = {
	metadata: 'a'.repeat(16),
	points: 'b'.repeat(16),
	redshift: 'c'.repeat(16)
};

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
	mask?: number;
	alias?: number;
	crossIds?: CrossId[];
}

function metadataTile(token: string, rows: MetaRow[], objectFile = true): Uint8Array {
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
			col('class', 'dict', (r) => (r.alias ? null : 'star')),
			col('class_source', 'dict', (r) => (r.alias ? null : 'gaia-dr3')),
			col('cross_ids', 'cross_ids', (r) => (r.alias ? null : (r.crossIds ?? []))),
			col('mask', 'uint32', (r) => r.mask ?? (r.alias ? 0 : 2)),
			...(objectFile ? [col('object_file', 'string', () => null)] : []),
			col('alias_target', 'id', (r) => r.alias ?? null)
		],
		tileInfoBytes(0, 0, 0)
	);
}

function dataTile(
	token: string,
	number: number,
	rows: { id: number; parallax: number }[]
): Uint8Array {
	return encode(
		KIND_TILE,
		token,
		rows.length,
		[
			{ name: 'id', type: 'id', values: rows.map((r) => r.id) },
			{ name: 'parallax', type: 'float32', values: rows.map((r) => r.parallax) },
			{ name: 'parallax_error', type: 'float32', values: rows.map(() => 0.1) }
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
	options: { metaDistribution?: string; objectFile?: boolean } = {}
): SyntheticExport {
	const meta: ExtrasolarMetadata = {
		format: 1,
		exported: '',
		registry: { ingest: 1, host: 'test' },
		tables: {
			metadata: table('metadata', null, TOKENS.metadata, options.metaDistribution),
			'point-source': table('point-source', 1, TOKENS.points),
			redshift: table('redshift', 2, TOKENS.redshift, 'site-only')
		},
		trees: {},
		credits: [{ name: 'Test catalogue', organisation: 'Test', source: 'https://example.org/' }]
	};
	const payloads: Record<string, Uint8Array> = {
		'metadata/split.bin.gz': split(TOKENS.metadata),
		'point-source/split.bin.gz': split(TOKENS.points),
		'redshift/split.bin.gz': split(TOKENS.redshift),
		'metadata/0/0.bin.gz': metadataTile(
			TOKENS.metadata,
			[
				{
					id: STAR,
					name: 'Test Star',
					crossIds: [{ catalogue: 'gaia', release: 'dr3', catalogueId: '42' }]
				},
				{ id: SECOND },
				{ id: ALIAS, alias: STAR },
				{ id: WITH_TABLE_2, mask: 2 | 4 }
			],
			options.objectFile
		),
		'point-source/0/0.bin.gz': dataTile(TOKENS.points, 1, [
			{ id: STAR, parallax: 379.21 },
			{ id: SECOND, parallax: 0.3 },
			{ id: WITH_TABLE_2, parallax: 2 }
		]),
		'redshift/0/0.bin.gz': dataTile(TOKENS.redshift, 2, [{ id: WITH_TABLE_2, parallax: 7 }])
	};
	return { meta, payloads };
}
