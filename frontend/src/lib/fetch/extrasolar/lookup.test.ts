import { describe, expect, it } from 'vitest';
import { Container } from './container';
import { ExtrasolarStaleError } from './files';
import {
	ExtrasolarLookup,
	hasDistance,
	homeRow,
	parallaxDistancePc,
	type LookupSource
} from './lookup';
import {
	ALIAS,
	RETIRED,
	SECOND,
	STAR,
	WITH_TABLE_2,
	idOf,
	syntheticExport
} from './__fixtures__/synthetic';
import { HAS_EXPORT, diskSource, own } from './__fixtures__/export';

// In level-0 pixel 0, the one tile of each synthetic table.
interface Synthetic {
	source: LookupSource & { reads: string[] };
	fail: Set<string>;
}

/** The synthetic export behind a lookup source. */
function synthetic(options: { metaDistribution?: string; tokenOff?: string } = {}): Synthetic {
	const { meta, payloads } = syntheticExport(options);
	const files = Object.fromEntries(
		Object.entries(payloads).map(([path, payload]) => [path, new Container(own(payload))])
	);
	const reads: string[] = [];
	const fail = new Set<string>();
	return {
		fail,
		source: {
			reads,
			metadata: async () => meta,
			file: async (path, token) => {
				reads.push(path);
				if (fail.has(path)) throw new Error(`${path} returned 503`);
				const file = files[path];
				if (!file) throw new Error(`${path} returned 404`);
				const found = options.tokenOff === path ? 'f'.repeat(16) : file.token;
				if (found !== token) throw new ExtrasolarStaleError(path, found, token);
				return file;
			},
			allowed: (entry) => entry.distribution !== 'site-only'
		}
	};
}

describe('ExtrasolarLookup on synthetic tiles', () => {
	it('fetches the Metadata row and the home row together, and only those', async () => {
		const { source } = synthetic();
		const result = await new ExtrasolarLookup(source).lookup(String(STAR));
		expect(result.kind).toBe('live');
		if (result.kind !== 'live') return;
		const { record } = result;
		expect(record.metadata.name).toBe('Test Star');
		expect(record.metadata.crossIds).toEqual([
			{ catalogue: 'gaia', release: 'dr3', catalogueId: '42' }
		]);
		expect(record.metadata.mask).toBe(2);
		expect(record.home).toBe('point-source');
		expect(homeRow(record)?.number('parallax')).toBeCloseTo(379.21, 4);
		expect(parallaxDistancePc(homeRow(record)!)).toBeCloseTo(1000 / 379.21, 4);
		expect(hasDistance(record)).toBe(true);
		expect(record.credits).toHaveLength(1);
		expect(new Set(source.reads)).toEqual(
			new Set([
				'metadata/split.bin.gz',
				'point-source/split.bin.gz',
				'metadata/0/0.bin.gz',
				'point-source/0/0.bin.gz'
			])
		);
	});

	it('fetches the other tables the mask names, where the host may show them', async () => {
		const { source } = synthetic();
		source.allowed = () => true;
		const result = await new ExtrasolarLookup(source).lookup(WITH_TABLE_2);
		expect(result.kind === 'live' && [...result.record.rows.keys()].sort()).toEqual([
			'point-source',
			'redshift'
		]);
		expect(result.kind === 'live' && result.record.rows.get('redshift')?.number('parallax')).toBe(
			7
		);

		const barred = synthetic();
		const second = await new ExtrasolarLookup(barred.source).lookup(WITH_TABLE_2);
		expect(second.kind === 'live' && [...second.record.rows.keys()]).toEqual(['point-source']);
		expect(barred.source.reads).not.toContain('redshift/0/0.bin.gz');
	});

	it('answers an alias with its live ID, and live() follows it', async () => {
		const { source } = synthetic();
		const lookup = new ExtrasolarLookup(source);
		expect(await lookup.lookup(ALIAS)).toEqual({ kind: 'alias', id: ALIAS, target: STAR });
		const live = await lookup.live(ALIAS);
		expect(live.kind === 'live' && live.record.id).toBe(STAR);
	});

	it('gives no page to an ID with no Metadata row, or one this export cannot hold', async () => {
		const lookup = new ExtrasolarLookup(synthetic().source);
		expect(await lookup.lookup(RETIRED)).toEqual({ kind: 'missing', reason: 'no-row' });
		expect(await lookup.lookup(idOf(0, 3))).toEqual({ kind: 'missing', reason: 'id' });
		expect(await lookup.lookup('0')).toEqual({ kind: 'missing', reason: 'id' });
		expect(await lookup.lookup('0' + STAR)).toEqual({ kind: 'missing', reason: 'id' });
		expect(await lookup.lookup(1.5)).toEqual({ kind: 'missing', reason: 'id' });
	});

	it('bars every ID where the host may not show the Metadata table', async () => {
		const lookup = new ExtrasolarLookup(synthetic({ metaDistribution: 'site-only' }).source);
		expect(await lookup.lookup(STAR)).toEqual({ kind: 'missing', reason: 'barred' });
	});

	it('answers unconfigured where the host has no export', async () => {
		const { source } = synthetic();
		source.metadata = async () => null;
		expect(await new ExtrasolarLookup(source).lookup(STAR)).toEqual({
			kind: 'missing',
			reason: 'unconfigured'
		});
	});

	it('reads only the Metadata table for a page title', async () => {
		const { source } = synthetic();
		const result = await new ExtrasolarLookup(source).lookup(STAR, { data: false });
		expect(result.kind === 'live' && result.record.rows.size).toBe(0);
		expect(source.reads.sort()).toEqual(['metadata/0/0.bin.gz', 'metadata/split.bin.gz']);
	});

	it('keeps the split tables and tiles, and a result', async () => {
		const { source } = synthetic();
		const lookup = new ExtrasolarLookup(source);
		await lookup.lookup(STAR);
		const after = source.reads.length;
		await lookup.lookup(SECOND);
		await lookup.lookup(STAR);
		expect(source.reads.length).toBe(after);
	});

	it('drops tiles past its limit, oldest first', async () => {
		const { source } = synthetic();
		const lookup = new ExtrasolarLookup(source, { tiles: 1, results: 1 });
		await lookup.lookup(STAR);
		const after = source.reads.length;
		await lookup.lookup(SECOND);
		expect(source.reads.length).toBe(after + 2);
	});

	it('keeps no failure: the next lookup reads again', async () => {
		const { source, fail } = synthetic();
		const lookup = new ExtrasolarLookup(source);
		fail.add('point-source/0/0.bin.gz');
		await expect(lookup.lookup(STAR)).rejects.toThrow('503');
		fail.clear();
		expect((await lookup.lookup(STAR)).kind).toBe('live');
	});

	it('rejects a file from another export', async () => {
		const lookup = new ExtrasolarLookup(synthetic({ tokenOff: 'metadata/0/0.bin.gz' }).source);
		await expect(lookup.lookup(STAR)).rejects.toBeInstanceOf(ExtrasolarStaleError);
	});
});

describe.skipIf(!HAS_EXPORT)('ExtrasolarLookup on the real export', () => {
	const lookup = new ExtrasolarLookup(diskSource());

	it.each([
		[22137869, 'Sirius', 379.21],
		[20593262, 'Vega', 130.23],
		[27424668, 'Proxima Centauri', 768.0665],
		[564339647, 'Toliman', 796.92],
		[7544072308, 'Gaia DR3 6103567647708210176', 3.3248],
		[27879543, 'Gaia DR3 6103569159536374400', 0.37097]
	])('finds %i (%s)', async (starId, name, parallax) => {
		const result = await lookup.lookup(String(starId));
		expect(result.kind).toBe('live');
		if (result.kind !== 'live') return;
		expect(result.record.metadata.name).toBe(name);
		expect(result.record.metadata.class).toBe('star');
		expect(result.record.metadata.mask).toBe(2);
		expect(result.record.metadata.aliasTarget).toBeNull();
		expect(homeRow(result.record)?.number('parallax')).toBeCloseTo(parallax, 3);
	});

	it('names the catalogue ids of Proxima', async () => {
		const result = await lookup.lookup('27424668');
		const ids = result.kind === 'live' ? result.record.metadata.crossIds : [];
		expect(ids).toContainEqual({
			catalogue: 'gaia',
			release: 'dr3',
			catalogueId: '5853498713190525696'
		});
		expect(ids).toContainEqual({ catalogue: 'hip', release: '2007', catalogueId: '70890' });
	});

	it('gives no distance to a Hipparcos star with a parallax under 5σ', async () => {
		const result = await lookup.lookup('16799379');
		expect(result.kind === 'live' && hasDistance(result.record)).toBe(false);
	});

	it.each([
		[String(999 * 2 ** 29 + 22137869), 'no-row'],
		[String(2 * 2 ** 24 + 5), 'id'],
		['022137869', 'id'],
		['9007199254740992', 'id']
	])('has no page for %s', async (text, reason) => {
		expect(await lookup.lookup(text)).toEqual({ kind: 'missing', reason });
	});

	it('bars the IDs where the host may not show non-commercial tables', async () => {
		const barred = new ExtrasolarLookup(diskSource((entry) => entry.distribution === undefined));
		expect(await barred.lookup('22137869')).toEqual({ kind: 'missing', reason: 'barred' });
	});
});
