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
	/** True when the site's object bundles hold an entry for the ID: its
	 *  names in other languages, its Wikidata and Wikipedia text, the papers
	 *  of its values. */
	object: boolean;
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

	/** A `uint64` column, exact past 2^53. */
	bigint(name: string): bigint | null {
		const c = this.container;
		if (!c.has(name) || !c.isValid(name, this.row)) return null;
		return c.uint64(name)[this.row];
	}

	/** A `float32_list` column, as a view on the tile; NaN entries stay. */
	floats(name: string): Float32Array | null {
		const c = this.container;
		if (!c.has(name)) return null;
		return c.float32List(name).get(this.row);
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
/** A Gaia row under this astrometric fidelity has a suspect parallax. */
const MIN_FIDELITY = 0.5;
/** The source of the values that the literature table gives. */
export const LITERATURE = 'literature';
/** The `distance_method` of a distance that a measured parallax gives. */
const MEASURED_PARALLAX = 'parallax';
/** How many times more precise than a Gaia parallax a group must be to win. */
const GAIA_MARGIN = 2;
/** SIMBAD's parallax, which on a row with its own is Gaia DR2's. */
const SIMBAD_PARALLAX = 'simbad-parallax';

/** The astrometry sources that the fidelity rates. */
const GAIA_ASTROMETRY = new Set(['gaia-dr3', 'gaia-dr3-named']);

export const BINARY_ORBIT_SLUG = 'binary-orbit';
/** Orbit solutions that fit the light centre's motion on the sky, with a
 *  parallax of their own. */
const ASTROMETRIC_SOLUTIONS = new Set([
	'AstroSpectroSB1',
	'OrbitalTargetedSearchValidated',
	'OrbitalAlternativeValidated',
	'Orbital',
	'OrbitalTargetedSearch',
	'OrbitalAlternative'
]);

/** The parallax that gives a star its distance, mas. */
export interface DistanceParallax {
	parallax: number;
	error: number;
	/** True when it is the parallax of the star's orbit solution. */
	fromOrbit: boolean;
}

/** The table-2 row of a record whose orbit solution is astrometric. */
export function astrometricOrbit(record: ExtrasolarRecord): TableRow | null {
	const orbit = record.rows.get(BINARY_ORBIT_SLUG);
	const type = orbit?.text('nss_solution_type');
	return orbit && type && ASTROMETRIC_SOLUTIONS.has(type) ? orbit : null;
}

/** The parallax of an orbit solution, where it is over 5 times its error. */
function orbitParallax(orbit: TableRow | null): DistanceParallax | null {
	const parallax = orbit?.number('parallax_nss') ?? null;
	const error = orbit?.number('parallax_nss_error') ?? null;
	if (parallax === null || error === null || !(parallax / error > MIN_PARALLAX_SNR)) return null;
	return { parallax, error, fromOrbit: true };
}

/**
 * The parallax of the row, where it is over 5 times its error, with the
 * parallax of the astrometric orbit solution in its place where that is also
 * over 5 times its error. `orbit` is the record's `astrometricOrbit`. It has
 * no default, so that no caller gets the single-star parallax by omission.
 */
export function distanceParallax(row: TableRow, orbit: TableRow | null): DistanceParallax | null {
	const parallax = row.number('parallax');
	const error = row.number('parallax_error');
	if (parallax === null || error === null || !(parallax / error > MIN_PARALLAX_SNR)) return null;
	return orbitParallax(orbit) ?? { parallax, error, fromOrbit: false };
}

/** A star's distance in pc and the bounds of its uncertainty. */
export interface StarDistance {
	pc: number;
	lower: number | null;
	upper: number | null;
	lowerPercentile: number | null;
	upperPercentile: number | null;
	/** `suspect parallax`: a 5σ Gaia parallax with an astrometric fidelity
	 *  under 0.5. `catalogue`: a planet host's distance in its exoplanet
	 *  catalogue. */
	from: 'parallax' | 'suspect parallax' | 'group' | 'catalogue';
	/** The catalogue of a distance from the distance group or of a planet host. */
	source: string | null;
	/** The parallax that gives the distance, where one does. */
	parallax: DistanceParallax | null;
}

function fromParallax(used: DistanceParallax, from: StarDistance['from']): StarDistance {
	const { parallax, error } = used;
	return {
		pc: 1000 / parallax,
		lower: 1000 / (parallax + error),
		upper: 1000 / (parallax - error),
		lowerPercentile: null,
		upperPercentile: null,
		from,
		source: null,
		parallax: used
	};
}

/**
 * The distance of a star by the rule of the render tree
 * (`docs/export-format/extrasolar.md`): a distance from a paper, a 5σ
 * parallax that is not flagged and that no more precise measured parallax in
 * the group beats, the distance group, a planet host's catalogue distance,
 * then a flagged 5σ parallax. A row is flagged when its Gaia astrometry has a
 * fidelity under 0.5. A flagged row has a distance only from a paper or when
 * Hipparcos, SIMBAD or an exoplanet catalogue saw it. `orbit` is the record's
 * `astrometricOrbit`, whose 5σ parallax stands for the row's.
 */
export function starDistance(row: TableRow, orbit: TableRow | null): StarDistance | null {
	const group = groupDistance(row);
	// A distance from a paper was chosen on purpose, so it beats any parallax.
	if (group?.source === LITERATURE) return group;
	const fidelity = row.number('fidelity_v2');
	const flagged =
		GAIA_ASTROMETRY.has(row.text('astrometry_source') ?? '') &&
		fidelity !== null &&
		fidelity < MIN_FIDELITY;
	const used = distanceParallax(row, orbit);
	if (used && !flagged && !(group && betterThanParallax(row, group))) {
		return fromParallax(used, 'parallax');
	}
	const seen =
		!flagged ||
		row.text('hipparcos_photometry_source') !== null ||
		row.text('simbad_photometry_source') !== null ||
		row.text('host_star_source') !== null;
	if (!seen) return null;
	return group ?? hostDistance(row, orbit) ?? (used && fromParallax(used, 'suspect parallax'));
}

/** Whether the group is a measured parallax more precise than the row's own.
 *  The distance catalogues copy Gaia's parallax with its error rounded down,
 *  so against Gaia astrometry the group must be twice as precise. SIMBAD's
 *  parallax and a distance from a prior or from a group of stars stay below
 *  the star's parallax. The single-star values decide, as for the 5σ test. */
function betterThanParallax(row: TableRow, group: StarDistance): boolean {
	const parallax = row.number('parallax');
	const error = row.number('parallax_error');
	if (row.text('distance_method') !== MEASURED_PARALLAX || group.source === SIMBAD_PARALLAX) {
		return false;
	}
	if (group.lower === null || group.upper === null || parallax === null || error === null) {
		return false;
	}
	const margin = GAIA_ASTROMETRY.has(row.text('astrometry_source') ?? '') ? GAIA_MARGIN : 1;
	return (margin * (group.upper - group.lower)) / (2 * group.pc) < error / parallax;
}

function groupDistance(row: TableRow): StarDistance | null {
	const distance = row.number('distance');
	if (distance === null || distance <= 0) return null;
	return {
		pc: distance,
		lower: row.number('distance_lower'),
		upper: row.number('distance_upper'),
		lowerPercentile: row.number('distance_lower_percentile'),
		upperPercentile: row.number('distance_upper_percentile'),
		from: 'group',
		source: row.text('distance_source'),
		parallax: null
	};
}

/** A planet host's distance in its exoplanet catalogue. A 5σ orbit parallax
 *  measures it better. */
function hostDistance(row: TableRow, orbit: TableRow | null): StarDistance | null {
	const pc = row.number('host_distance');
	if (pc === null || pc <= 0) return null;
	const fromOrbit = orbitParallax(orbit);
	if (fromOrbit) return fromParallax(fromOrbit, 'parallax');
	const error = row.number('host_distance_error');
	return {
		pc,
		lower: error === null || error >= pc ? null : pc - error,
		upper: error === null ? null : pc + error,
		lowerPercentile: null,
		upperPercentile: null,
		from: 'catalogue',
		source: row.text('host_star_source'),
		parallax: null
	};
}

/** The home row of a record, where it has one. */
export function homeRow(record: ExtrasolarRecord): TableRow | null {
	return (record.home && record.rows.get(record.home)) || null;
}

/** Whether the record places the object in 3D. */
export function hasDistance(record: ExtrasolarRecord): boolean {
	const home = homeRow(record);
	return home !== null && starDistance(home, astrometricOrbit(record)) !== null;
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
		object: c.has('object') && c.isValid('object', row) && c.bool('object')[row] === 1,
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
