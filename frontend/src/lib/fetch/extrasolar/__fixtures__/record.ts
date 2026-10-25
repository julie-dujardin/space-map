/**
 * Test-only star record with one Point source row of the given columns, for
 * panel code that needs no lookup.
 */

import { Container, KIND_TILE } from '../container';
import type { ExtrasolarCredit, ExtrasolarTable } from '../files';
import { TableRow, type ExtrasolarRecord } from '../lookup';
import { own } from './export';
import { encode, tileInfoBytes, type ColumnSpec } from './writer';

const SLUG = 'point-source';
const TOKEN = 'b'.repeat(16);

export function pointSourceRecord(
	columns: ColumnSpec[],
	credits: ExtrasolarCredit[] = []
): ExtrasolarRecord {
	const bytes = encode(
		KIND_TILE,
		TOKEN,
		1,
		[{ name: 'id', type: 'id', values: [1] }, ...columns],
		tileInfoBytes(0, 0, 1)
	);
	const table = { number: 1, token: TOKEN, columns: [] } as unknown as ExtrasolarTable;
	return {
		id: 1,
		metadata: {
			id: 1,
			name: null,
			nameSource: null,
			class: 'star',
			classSource: null,
			crossIds: [],
			mask: 2,
			object: false,
			aliasTarget: null
		},
		rows: new Map([[SLUG, new TableRow(SLUG, table, new Container(own(bytes)), 0)]]),
		home: SLUG,
		credits
	};
}
