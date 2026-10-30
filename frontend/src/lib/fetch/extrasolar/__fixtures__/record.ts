/**
 * Test-only records for code that needs no lookup. A star has one Point source
 * row of the given columns, and a Binary orbit row where `orbit` gives its
 * columns. A star system node has a System row.
 */

import { Container, KIND_TILE } from '../container';
import type { ExtrasolarCredit, ExtrasolarTable } from '../files';
import { SYSTEM_SLUG, TableRow, type ExtrasolarRecord } from '../lookup';
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
export function valueColumns(values: Record<string, number | string>): ColumnSpec[] {
	return Object.entries(values).map(([name, value]) => ({
		name,
		type: typeof value === 'number' ? 'float32' : 'dict',
		values: [value]
	}));
}

export function pointSourceRecord(
	columns: ColumnSpec[],
	credits: ExtrasolarCredit[] = [],
	orbit?: ColumnSpec[]
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
			object: false,
			aliasTarget: null
		},
		rows: new Map([[SYSTEM_SLUG, systemRow(primary)]]),
		home: SYSTEM_SLUG,
		credits: []
	};
}
