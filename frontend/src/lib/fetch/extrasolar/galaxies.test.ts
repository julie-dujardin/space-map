import { describe, expect, it } from 'vitest';
import { Container } from './container';
import { catalogueCounts, galaxyRow, isGalaxy } from './galaxies';
import { ExtrasolarLookup, hasDistance, homeRow, starDistance, type LookupSource } from './lookup';
import { own } from './__fixtures__/export';
import { ABOUT_KINDS, GALAXY, galaxyExport, galaxyRecord } from './__fixtures__/galaxy';
import { pointSourceRecord } from './__fixtures__/record';
import { idOf } from './__fixtures__/synthetic';

/** The galaxy export behind a lookup source, with the paths it reads. */
function source(): LookupSource & { reads: string[] } {
	const { meta, payloads } = galaxyExport();
	const files = Object.fromEntries(
		Object.entries(payloads).map(([path, payload]) => [path, new Container(own(payload))])
	);
	const reads: string[] = [];
	return {
		reads,
		metadata: async () => meta,
		file: async (path) => {
			reads.push(path);
			const file = files[path];
			if (!file) throw new Error(`${path} returned 404`);
			return file;
		},
		allowed: () => true
	};
}

describe('the lookup of a galaxy', () => {
	it('reads its Metadata row and its Redshift row, the home table that metadata.json names', async () => {
		const from = source();
		const result = await new ExtrasolarLookup(from).lookup(String(GALAXY));
		expect(result.kind).toBe('live');
		if (result.kind !== 'live') return;
		const { record } = result;
		expect(record.home).toBe('redshift');
		expect(record.metadata.class).toBe('galaxy');
		expect(record.metadata.mask).toBe(16);
		expect(record.metadata.object).toBe(true);
		expect([...record.rows.keys()]).toEqual(['redshift']);
		expect(isGalaxy(record)).toBe(true);
		expect(new Set(from.reads)).toEqual(
			new Set([
				'metadata/split.bin.gz',
				'redshift/split.bin.gz',
				'metadata/0/0.bin.gz',
				'redshift/0/0.bin.gz'
			])
		);
	});

	it('gives no page to a table-4 ID that was never minted', async () => {
		const result = await new ExtrasolarLookup(source()).lookup(String(idOf(7, 4)));
		expect(result).toEqual({ kind: 'missing', reason: 'no-row' });
	});

	it('knows no table 4 in an export from before the galaxies', async () => {
		const from = source();
		const meta = (await from.metadata())!;
		const tables = Object.fromEntries(
			Object.entries(meta.tables).filter(([slug]) => slug !== 'redshift')
		);
		from.metadata = async () => ({ ...meta, tables });
		const result = await new ExtrasolarLookup(from).lookup(String(GALAXY));
		expect(result).toEqual({ kind: 'missing', reason: 'id' });
	});
});

describe('the Redshift row of a galaxy', () => {
	it('reads each column group, a float32 at the figures it holds', async () => {
		const result = await new ExtrasolarLookup(source()).lookup(GALAXY);
		const row = result.kind === 'live' ? galaxyRow(result.record) : null;
		expect(row).toEqual({
			ra: 266.4168076,
			dec: -29.007839,
			distance: { value: 8277, lower: 8243, upper: 8311 },
			distanceMethod: 'dynamical',
			morphologicalType: 'SAB(rs)bc',
			stellarMass: { value: 5.04e10, lower: 4.52e10, upper: 5.47e10 },
			totalMass: { value: 1.08e12, lower: 0.94e12, upper: 1.28e12 },
			starFormationRate: { value: 1.65, lower: 1.46, upper: 1.84 }
		});
	});

	it('leaves a group with no value null', () => {
		const row = galaxyRow(
			galaxyRecord([
				{ name: 'ra', type: 'float64', values: [10] },
				{ name: 'dec', type: 'float64', values: [20] },
				{ name: 'stellar_mass', type: 'float32', values: [null] }
			])
		);
		expect(row).toMatchObject({ ra: 10, distance: null, stellarMass: null, totalMass: null });
		expect(row?.morphologicalType).toBeNull();
	});

	it('is null for a star, and for a galaxy whose table the host may not show', () => {
		expect(galaxyRow(pointSourceRecord([]))).toBeNull();
		expect(isGalaxy(pointSourceRecord([]))).toBe(false);
		expect(galaxyRow({ ...galaxyRecord(), rows: new Map() })).toBeNull();
	});

	it('places the galaxy as a star is placed, at the distance of its point', () => {
		const record = galaxyRecord();
		expect(hasDistance(record)).toBe(true);
		expect(starDistance(homeRow(record)!, null)).toMatchObject({
			pc: 8277,
			lower: 8243,
			upper: 8311,
			source: 'galaxy-literature'
		});
	});
});

describe('what the catalogue holds', () => {
	it('counts the stars, the star systems and the planets as /about/data does', () => {
		expect(catalogueCounts(ABOUT_KINDS)).toEqual({
			stars: 180_622_691,
			starSystems: 1_689_592,
			planets: 7_538
		});
	});

	it('has no count for a kind that the report lacks', () => {
		expect(catalogueCounts([{ id: 'star', count: 3 }])).toEqual({
			stars: 3,
			starSystems: null,
			planets: null
		});
	});
});
