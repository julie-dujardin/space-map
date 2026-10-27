import { describe, expect, it } from 'vitest';
import { Container } from './container';
import { ExtrasolarStaleError } from './files';
import {
	ExtrasolarLookup,
	astrometricOrbit,
	distanceParallax,
	hasDistance,
	homeRow,
	starDistance,
	type LookupSource
} from './lookup';
import {
	ALIAS,
	ORBIT_FLAGS,
	RETIRED,
	SECOND,
	STAR,
	WITH_TABLE_2,
	idOf,
	pointSourceRow,
	syntheticExport,
	type ObjectColumn
} from './__fixtures__/synthetic';
import { HAS_EXPORT, diskSource, own } from './__fixtures__/export';
import { pointSourceRecord } from './__fixtures__/record';
import type { ColumnSpec } from './__fixtures__/writer';

// In level-0 pixel 0, the one tile of each synthetic table.
interface Synthetic {
	source: LookupSource & { reads: string[] };
	fail: Set<string>;
}

/** The synthetic export behind a lookup source. */
function synthetic(
	options: { metaDistribution?: string; tokenOff?: string; objectColumn?: ObjectColumn } = {}
): Synthetic {
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
			{ catalogue: 'gaia', release: 'dr3', catalogueId: '42' },
			{ catalogue: 'wikidata', release: 'qid', catalogueId: 'Q86' }
		]);
		expect(record.metadata.mask).toBe(2);
		expect(record.metadata.object).toBe(true);
		expect(record.home).toBe('point-source');
		expect(homeRow(record)?.number('parallax')).toBeCloseTo(379.21, 4);
		expect(starDistance(homeRow(record)!, null)?.pc).toBeCloseTo(1000 / 379.21, 4);
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
			'binary-orbit',
			'point-source'
		]);
		const orbit = result.kind === 'live' ? result.record.rows.get('binary-orbit') : undefined;
		expect(orbit?.number('parallax')).toBe(7);
		expect(orbit?.text('nss_solution_type')).toBe('Orbital');
		expect(orbit?.bigint('flags')).toBe(ORBIT_FLAGS);
		const vector = orbit?.floats('corr_vec');
		expect(vector && [vector[0], Number.isNaN(vector[1]), vector[2], vector.length]).toEqual([
			0.5,
			true,
			-0.25,
			3
		]);
		expect(orbit?.floats('no_such_column')).toBeNull();

		const barred = synthetic();
		const second = await new ExtrasolarLookup(barred.source).lookup(WITH_TABLE_2);
		expect(second.kind === 'live' && [...second.record.rows.keys()]).toEqual(['point-source']);
		expect(barred.source.reads).not.toContain('binary-orbit/0/0.bin.gz');
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

	it('reads exports from before the object column', async () => {
		const result = await new ExtrasolarLookup(
			synthetic({ objectColumn: 'object_file' }).source
		).lookup(STAR);
		expect(result.kind === 'live' && result.record.metadata.object).toBe(false);
	});

	it('reads exports from before object files were added', async () => {
		const result = await new ExtrasolarLookup(synthetic({ objectColumn: 'none' }).source).lookup(
			STAR
		);
		expect(result.kind === 'live' && result.record.metadata.object).toBe(false);
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

describe('the distance of a binary star', () => {
	const single = (parallax: number, error: number): ColumnSpec[] => [
		{ name: 'parallax', type: 'float32', values: [parallax] },
		{ name: 'parallax_error', type: 'float32', values: [error] }
	];
	const orbit = (type: string, parallax: number, error: number): ColumnSpec[] => [
		{ name: 'nss_solution_type', type: 'dict', values: [type] },
		{ name: 'parallax_nss', type: 'float32', values: [parallax] },
		{ name: 'parallax_nss_error', type: 'float32', values: [error] }
	];

	it('takes the parallax of an astrometric orbit solution', () => {
		for (const type of ['Orbital', 'AstroSpectroSB1', 'OrbitalTargetedSearchValidated']) {
			const record = pointSourceRecord(single(10, 0.125), [], orbit(type, 12.5, 0.0625));
			const solution = astrometricOrbit(record);
			expect(solution, type).not.toBeNull();
			expect(distanceParallax(homeRow(record)!, solution)).toEqual({
				parallax: 12.5,
				error: 0.0625,
				fromOrbit: true
			});
			expect(starDistance(homeRow(record)!, solution)?.pc).toBe(80);
		}
	});

	it('keeps the single-star parallax for another solution or a weak orbit parallax', () => {
		const spectroscopic = pointSourceRecord(single(10, 0.125), [], orbit('SB1', 12.5, 0.0625));
		expect(astrometricOrbit(spectroscopic)).toBeNull();
		const weak = pointSourceRecord(single(10, 0.125), [], orbit('Orbital', 0.5, 0.125));
		expect(distanceParallax(homeRow(weak)!, astrometricOrbit(weak))).toEqual({
			parallax: 10,
			error: 0.125,
			fromOrbit: false
		});
		expect(starDistance(homeRow(weak)!, null)?.pc).toBe(100);
	});

	it('gives no distance where the single-star parallax gives none, as the tree draws none', () => {
		const record = pointSourceRecord(single(0.5, 0.125), [], orbit('Orbital', 12.5, 0.0625));
		expect(starDistance(homeRow(record)!, astrometricOrbit(record))).toBeNull();
	});

	it("gives a planet host the orbit parallax before its catalogue's distance", () => {
		const host: ColumnSpec[] = [
			...single(0.5, 0.125),
			{ name: 'host_distance', type: 'float32', values: [70] },
			{ name: 'host_star_source', type: 'dict', values: ['nasa-exoplanet-archive'] }
		];
		const record = pointSourceRecord(host, [], orbit('Orbital', 12.5, 0.0625));
		const distance = starDistance(homeRow(record)!, astrometricOrbit(record));
		expect(distance && [distance.from, distance.pc]).toEqual(['parallax', 80]);
		expect(starDistance(homeRow(record)!, null)?.from).toBe('catalogue');
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
		[String(30 * 2 ** 24 + 5), 'id'],
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

describe("a star's distance, by the render tree's rule", () => {
	const from = (values: Record<string, number | string>) => {
		const distance = starDistance(pointSourceRow(values), null);
		return distance && [distance.from, distance.pc, distance.source];
	};
	const parallax = { parallax: 10, parallax_error: 0.1 };
	const group = { distance: 50, distance_source: 'hunt-reffert-2024' };
	const suspect = { astrometry_source: 'gaia-dr3', fidelity_v2: 0.1 };
	const flagged = { ...suspect, simbad_photometry_source: 'simbad' };

	it('takes a trusted 5σ parallax before the group', () => {
		expect(from({ ...parallax, ...group })).toEqual(['parallax', 100, null]);
		expect(from({ ...parallax, ...group, fidelity_v2: 0.5 })).toEqual(['parallax', 100, null]);
	});

	it("takes a measured parallax in the group that is more precise than the row's", () => {
		// α Cen B: Hipparcos 2007 ±3%, the 10 pc sample ±0.2%.
		const toliman = {
			astrometry_source: 'hipparcos-2007',
			parallax: 796.92,
			parallax_error: 25.9,
			distance: 1.3459,
			distance_lower: 1.3435,
			distance_upper: 1.3483,
			distance_source: 'reyle-2021',
			distance_method: 'parallax'
		};
		expect(from(toliman)?.[0]).toBe('group');
		expect(from(toliman)?.[1]).toBeCloseTo(1.3459, 4);
		const looser = { distance_lower: 45, distance_upper: 55, distance_method: 'parallax' };
		expect(from({ ...parallax, ...group, ...looser })).toEqual(['parallax', 100, null]);
	});

	it('takes the group over a Gaia parallax only when it is twice as precise', () => {
		const reyle = { distance: 50, distance_source: 'reyle-2021', distance_method: 'parallax' };
		const gaia = { ...parallax, astrometry_source: 'gaia-dr3' };
		const tight = { distance_lower: 49.8, distance_upper: 50.2 };
		const close = { distance_lower: 49.6, distance_upper: 50.4 };
		expect(from({ ...gaia, ...reyle, ...tight })?.[0]).toBe('group');
		expect(from({ ...gaia, ...reyle, ...close })?.[0]).toBe('parallax');
		const simbad = { ...parallax, astrometry_source: 'simbad' };
		expect(from({ ...simbad, ...reyle, ...close })?.[0]).toBe('group');
	});

	it("never takes SIMBAD's parallax over the row's own", () => {
		const simbadParallax = {
			distance: 50,
			distance_lower: 49.9,
			distance_upper: 50.1,
			distance_source: 'simbad-parallax',
			distance_method: 'parallax'
		};
		expect(from({ ...parallax, ...simbadParallax })).toEqual(['parallax', 100, null]);
	});

	it('keeps the parallax before a more precise distance from a prior or a cluster', () => {
		const tight = { distance_lower: 49.9, distance_upper: 50.1 };
		for (const distance_method of ['geometric', 'cluster']) {
			expect(from({ ...parallax, ...group, ...tight, distance_method })).toEqual([
				'parallax',
				100,
				null
			]);
		}
	});

	it('takes a distance from a paper before any parallax', () => {
		const paper = { distance: 2350, distance_source: 'literature' };
		expect(from({ ...parallax, ...paper })).toEqual(['group', 2350, 'literature']);
		expect(from({ ...parallax, ...paper, ...flagged })).toEqual(['group', 2350, 'literature']);
	});

	it('takes the group where the parallax is under 5σ', () => {
		const weak = { parallax: 0.1, parallax_error: 0.1 };
		expect(from({ ...weak, ...group })).toEqual(['group', 50, 'hunt-reffert-2024']);
		expect(from(weak)).toBeNull();
	});

	it("keeps a distance group's published percentiles", () => {
		const distance = starDistance(
			pointSourceRow({
				distance: 1220,
				distance_lower: 1200,
				distance_upper: 1230,
				distance_lower_percentile: 2.5,
				distance_upper_percentile: 97.5,
				distance_source: 'literature'
			}),
			null
		);
		expect(distance).toMatchObject({ lowerPercentile: 2.5, upperPercentile: 97.5 });
	});

	it('takes the group before a parallax under 0.5 fidelity, then the parallax', () => {
		expect(from({ ...parallax, ...group, ...flagged })).toEqual(['group', 50, 'hunt-reffert-2024']);
		expect(from({ ...parallax, ...flagged })).toEqual(['suspect parallax', 100, null]);
	});

	it('gives no distance under 0.5 fidelity without a Hipparcos, SIMBAD or planet match', () => {
		expect(from({ ...parallax, ...group, ...suspect })).toBeNull();
		const hipparcos = { ...suspect, hipparcos_photometry_source: 'hipparcos-2007' };
		expect(from({ ...parallax, ...hipparcos })?.[0]).toBe('suspect parallax');
		const paper = { distance: 2350, distance_source: 'literature' };
		expect(from({ ...parallax, ...suspect, ...paper })).toEqual(['group', 2350, 'literature']);
	});

	it('flags only a Gaia parallax', () => {
		const hipparcos = { astrometry_source: 'hipparcos-2007', fidelity_v2: 0.1 };
		expect(from({ ...parallax, ...group, ...hipparcos })).toEqual(['parallax', 100, null]);
	});

	it("takes a planet host's catalogue distance after the group, before a suspect parallax", () => {
		const host = {
			host_distance: 40,
			host_distance_error: 2,
			host_star_source: 'nasa-exoplanet-archive'
		};
		expect(from({ ...host })).toEqual(['catalogue', 40, 'nasa-exoplanet-archive']);
		expect(starDistance(pointSourceRow(host), null)).toMatchObject({ lower: 38, upper: 42 });
		expect(from({ ...host, ...group })).toEqual(['group', 50, 'hunt-reffert-2024']);
		expect(from({ ...host, ...parallax, ...suspect })).toEqual([
			'catalogue',
			40,
			'nasa-exoplanet-archive'
		]);
	});
});
