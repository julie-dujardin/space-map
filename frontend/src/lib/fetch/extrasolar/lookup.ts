/**
 * The records of one extrasolar ID (`docs/export-format/extrasolar.md`,
 * "Lookup of an ID").
 *
 * The ID names its home table and its cell. The split tables of Metadata and
 * of the home table give the tile of the cell in each, and the two tiles are
 * fetched together. No Metadata row: the ID is not live. An alias row names
 * the live ID. The mask names the other tables with a row, at the same cell,
 * fetched in parallel.
 *
 * Split tables are kept per table token; tiles and results in small LRUs. A
 * failed fetch is not kept, so the next lookup tries again.
 */

import type { Container, CrossId } from './container';
import {
	extrasolarAllowed,
	extrasolarPath,
	fetchExtrasolarFile,
	fetchExtrasolarMetadata,
	type ExtrasolarCredit,
	type ExtrasolarMetadata,
	type ExtrasolarTable
} from './files';
import { FIRST_TABLE, LAST_TABLE, cellOf, parseExtrasolarId, tableOf } from './ids';
import { SplitTree, findId } from './split';
import { LruPromiseCache } from '$lib/fetch/position/cache';

export const METADATA_SLUG = 'metadata';

/** A row of the Metadata table. */
export interface MetadataRow {
	id: number;
	name: string | null;
	nameSource: string | null;
	class: string | null;
	classSource: string | null;
	crossIds: CrossId[];
	/** Bit n is set when data table n has a row for the ID. */
	mask: number;
	objectFile: string | null;
	/** The live ID of an alias; null for a live ID. */
	aliasTarget: number | null;
}

/** One row of a data table, read by column name. */
export class TableRow {
	constructor(
		readonly slug: string,
		readonly table: ExtrasolarTable,
		readonly container: Container,
		readonly row: number
	) {}

	has(name: string): boolean {
		return this.container.has(name);
	}

	/** A numeric column; null for no value, a NaN included. */
	number(name: string): number | null {
		const c = this.container;
		if (!c.has(name) || !c.isValid(name, this.row)) return null;
		let value: number;
		switch (c.type(name)) {
			case 'float32':
				value = c.float32(name)[this.row];
				break;
			case 'float64':
				value = c.float64(name)[this.row];
				break;
			case 'int8':
				value = c.int8(name)[this.row];
				break;
			case 'int16':
				value = c.int16(name)[this.row];
				break;
			case 'int32':
				value = c.int32(name)[this.row];
				break;
			case 'uint8':
				value = c.uint8(name)[this.row];
				break;
			case 'uint16':
				value = c.uint16(name)[this.row];
				break;
			case 'uint32':
				value = c.uint32(name)[this.row];
				break;
			case 'id':
				value = c.ids(name)[this.row];
				break;
			default:
				throw new Error(`${this.slug}.${name} is not a number column`);
		}
		return Number.isNaN(value) ? null : value;
	}

	/** A string or dictionary column. */
	text(name: string): string | null {
		const c = this.container;
		if (!c.has(name)) return null;
		const type = c.type(name);
		if (type === 'dict') return c.dict(name).get(this.row);
		if (type === 'string') return c.strings(name).get(this.row);
		throw new Error(`${this.slug}.${name} is not a text column`);
	}

	flag(name: string): boolean | null {
		const c = this.container;
		if (!c.has(name) || !c.isValid(name, this.row)) return null;
		return c.bool(name)[this.row] === 1;
	}
}

export interface ExtrasolarRecord {
	id: number;
	metadata: MetadataRow;
	/** Rows by table slug: the home table's, and those the mask names. */
	rows: ReadonlyMap<string, TableRow>;
	/** Slug of the home table. */
	home: string | null;
	/** The export's credits for its catalogues. */
	credits: readonly ExtrasolarCredit[];
}

/** Why an ID has no page. */
export type MissingReason =
	/** The host serves no extrasolar export. */
	| 'unconfigured'
	/** Not an ID of this export. */
	| 'id'
	/** The host may not show the Metadata table. */
	| 'barred'
	/** Never minted, or retired. */
	| 'no-row';

export type ExtrasolarLookupResult =
	| { kind: 'live'; record: ExtrasolarRecord }
	| { kind: 'alias'; id: number; target: number }
	| { kind: 'missing'; reason: MissingReason };

export interface LookupOptions {
	/** False: only the Metadata row, which is all that a page title needs. */
	data?: boolean;
}

/** Where the lookup reads the export. */
export interface LookupSource {
	metadata(): Promise<ExtrasolarMetadata | null>;
	/** A file, decoded, its header token checked against `token`. */
	file(path: string, token: string): Promise<Container>;
	allowed(entry: { distribution?: string }): boolean;
}

export interface LookupLimits {
	tiles: number;
	results: number;
}

const DEFAULT_LIMITS: LookupLimits = { tiles: 32, results: 64 };

/** A parallax under this many times its error gives no distance. */
const MIN_PARALLAX_SNR = 5;

/** Distance from a row's parallax, pc; null when it gives none. The render
 *  tree places a star by the same rule. */
export function parallaxDistancePc(row: TableRow): number | null {
	const parallax = row.number('parallax');
	const error = row.number('parallax_error');
	if (parallax === null || error === null || !(parallax / error > MIN_PARALLAX_SNR)) return null;
	return 1000 / parallax;
}

/** The home row of a record, where it has one. */
export function homeRow(record: ExtrasolarRecord): TableRow | null {
	return (record.home && record.rows.get(record.home)) || null;
}

/** Whether the record places the object in 3D. */
export function hasDistance(record: ExtrasolarRecord): boolean {
	const home = homeRow(record);
	return home !== null && parallaxDistancePc(home) !== null;
}

export function readMetadataRow(c: Container, row: number): MetadataRow {
	const alias = c.isValid('alias_target', row) ? c.ids('alias_target')[row] : 0;
	return {
		id: c.ids('id')[row],
		name: c.strings('name').get(row),
		nameSource: c.dict('name_source').get(row),
		class: c.dict('class').get(row),
		classSource: c.dict('class_source').get(row),
		crossIds: c.crossIds('cross_ids').get(row) ?? [],
		mask: c.uint32('mask')[row],
		objectFile: c.has('object_file') ? c.strings('object_file').get(row) : null,
		aliasTarget: alias > 0 ? alias : null
	};
}

interface NumberedTable {
	slug: string;
	table: ExtrasolarTable;
}

export class ExtrasolarLookup {
	private readonly splits = new Map<string, Promise<SplitTree>>();
	private readonly tiles: LruPromiseCache<Container>;
	private readonly results: LruPromiseCache<ExtrasolarLookupResult>;

	constructor(
		private readonly source: LookupSource,
		limits: LookupLimits = DEFAULT_LIMITS
	) {
		this.tiles = new LruPromiseCache(limits.tiles);
		this.results = new LruPromiseCache(limits.results);
	}

	/** The records of the live ID that `id` names: its own, or its alias
	 *  target's. Chains are collapsed at export, so one hop is enough. */
	async live(id: string | number, options: LookupOptions = {}): Promise<ExtrasolarLookupResult> {
		const first = await this.lookup(id, options);
		return first.kind === 'alias' ? this.lookup(first.target, options) : first;
	}

	/** The records of an ID, from its URL text or as a number. Rejects when a
	 *  file does not load; a `missing` result is the export's answer. */
	lookup(id: string | number, options: LookupOptions = {}): Promise<ExtrasolarLookupResult> {
		const data = options.data ?? true;
		return this.results.getOrCompute(`${id}:${data}`, () => this.resolve(String(id), data));
	}

	private async resolve(text: string, data: boolean): Promise<ExtrasolarLookupResult> {
		const meta = await this.source.metadata();
		if (!meta) return { kind: 'missing', reason: 'unconfigured' };
		const numbered = new Map<number, NumberedTable>();
		for (const [slug, table] of Object.entries(meta.tables)) {
			if (table.number !== null) numbered.set(table.number, { slug, table });
		}
		const id = parseExtrasolarId(text, new Set(numbered.keys()));
		if (id === null) return { kind: 'missing', reason: 'id' };
		const metaTable = meta.tables[METADATA_SLUG];
		if (!metaTable || !this.source.allowed(metaTable)) return { kind: 'missing', reason: 'barred' };

		const cell = cellOf(id);
		const home = numbered.get(tableOf(id))!;
		const homeShown = data && this.source.allowed(home.table);
		const [metaTile, homeTile] = await Promise.all([
			this.tile(METADATA_SLUG, metaTable, cell),
			homeShown ? this.tile(home.slug, home.table, cell) : null
		]);
		const metaRow = findId(metaTile.ids('id'), id);
		if (metaRow < 0) return { kind: 'missing', reason: 'no-row' };
		const metadata = readMetadataRow(metaTile, metaRow);
		if (metadata.aliasTarget !== null) {
			return { kind: 'alias', id, target: metadata.aliasTarget };
		}

		const rows = new Map<string, TableRow>();
		const adopt = (entry: NumberedTable, tile: Container) => {
			const row = findId(tile.ids('id'), id);
			if (row >= 0) rows.set(entry.slug, new TableRow(entry.slug, entry.table, tile, row));
		};
		if (homeTile) adopt(home, homeTile);
		if (data) {
			const others: NumberedTable[] = [];
			for (let n = FIRST_TABLE; n <= LAST_TABLE; n++) {
				const entry = numbered.get(n);
				if (!((metadata.mask >>> n) & 1) || !entry || entry === home) continue;
				if (this.source.allowed(entry.table)) others.push(entry);
			}
			const tiles = await Promise.all(
				others.map((entry) => this.tile(entry.slug, entry.table, cell))
			);
			others.forEach((entry, i) => adopt(entry, tiles[i]));
		}
		return {
			kind: 'live',
			record: { id, metadata, rows, home: home.slug, credits: meta.credits }
		};
	}

	private split(slug: string, table: ExtrasolarTable): Promise<SplitTree> {
		const key = `${slug}?v=${table.token}`;
		const held = this.splits.get(key);
		if (held) return held;
		const p = this.source
			.file(table.split, table.token)
			.then((c) => SplitTree.fromBits(c.bits('split')));
		this.splits.set(key, p);
		p.catch(() => {
			if (this.splits.get(key) === p) this.splits.delete(key);
		});
		return p;
	}

	private async tile(slug: string, table: ExtrasolarTable, cell: number): Promise<Container> {
		const split = await this.split(slug, table);
		const path = extrasolarPath(table.tile, split.tileOf(cell));
		return this.tiles.getOrCompute(`${path}?v=${table.token}`, () =>
			this.source.file(path, table.token)
		);
	}
}

/** The page's lookup, over the host's extrasolar URL. A file from another
 *  export than `metadata.json` prompts the reload on its own. */
export const extrasolarLookup = new ExtrasolarLookup({
	metadata: fetchExtrasolarMetadata,
	file: (path, token) => fetchExtrasolarFile(path, token),
	allowed: extrasolarAllowed
});
