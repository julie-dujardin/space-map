/**
 * The Interior table on a synthetic export: a fitted row and a curated row in
 * one tile, read through the lookup and gated by the host's ladder.
 */

import { afterEach, describe, expect, it } from 'vitest';
import { configureHost } from '$lib/host';
import { Container, KIND_SPLIT, KIND_TILE } from './container';
import { extrasolarAllowed, type ExtrasolarTable } from './files';
import { INTERIOR_SLUG, fetchStarInterior } from './interior';
import { ExtrasolarLookup, type LookupSource } from './lookup';
import { SECOND, STAR, WITH_TABLE_2, syntheticExport } from './__fixtures__/synthetic';
import { own } from './__fixtures__/export';
import { encode, tileInfoBytes, type ColumnSpec } from './__fixtures__/writer';

const TOKEN = 'e'.repeat(16);
const CURATED = {
	structure: 'fluid',
	layers: [
		{ role: 'radiative_zone', outer_radius_km: 1000, state: 'plasma', composition: [] },
		{ role: 'convective_core', state: 'plasma', composition: [] }
	],
	sources: [{ title: 'Paper 2002 (A&A 1)', url: 'https://doi.org/10.1/x' }]
};

function columns(): ColumnSpec[] {
	const two = <T>(fitted: T, curated: T | null) => [fitted, curated];
	return [
		{ name: 'id', type: 'id', values: [STAR, SECOND] },
		{ name: 'tier', type: 'int8', values: [2, 0] },
		{ name: 'curated', type: 'string', values: two(null, JSON.stringify(CURATED)) },
		{ name: 'stage', type: 'dict', values: two('main_sequence', null) },
		{ name: 'feh', type: 'float32', values: two(0.04, null) },
		{ name: 'feh_source', type: 'dict', values: two('pastel-2020', null) },
		{ name: 'teff_source', type: 'dict', values: two('flower-1996', null) },
		{ name: 'luminosity_source', type: 'dict', values: two('radius', null) },
		{ name: 'mass', type: 'float32', values: two(2.25, null) },
		{ name: 'mass_lower', type: 'float32', values: two(2, null) },
		{ name: 'mass_upper', type: 'float32', values: two(2.5, null) },
		{ name: 'radius', type: 'float32', values: two(1.75, null) },
		{ name: 'radius_lower', type: 'float32', values: two(1.5, null) },
		{ name: 'radius_upper', type: 'float32', values: two(2, null) },
		{ name: 'envelope_base_radius', type: 'float32', values: two(0.5, null) },
		{ name: 'envelope_base_radius_lower', type: 'float32', values: two(0.25, null) },
		{ name: 'envelope_base_radius_upper', type: 'float32', values: two(0.75, null) },
		{ name: 'convective_core_mass_lower', type: 'float32', values: two(0.25, null) },
		{ name: 'convective_core_mass_upper', type: 'float32', values: two(0.5, null) },
		{ name: 'centre_temperature', type: 'float32', values: two(2.5e7, null) },
		{ name: 'centre_temperature_lower', type: 'float32', values: two(2e7, null) },
		{ name: 'centre_temperature_upper', type: 'float32', values: two(3e7, null) },
		{ name: 'centre_x_lower', type: 'float32', values: two(0.125, null) },
		{ name: 'centre_x_upper', type: 'float32', values: two(0.5, null) }
	];
}

/** The synthetic export with an Interior table of `distribution`, and the
 *  paths that its lookup reads. */
function source(distribution: string): LookupSource & { reads: string[] } {
	const { meta, payloads } = syntheticExport();
	const interior: ExtrasolarTable = {
		number: null,
		token: TOKEN,
		split: `${INTERIOR_SLUG}/split.bin.gz`,
		tile: `${INTERIOR_SLUG}/{level}/{pixel}.bin.gz`,
		max_rows: 1500,
		rows: 2,
		tiles: 12,
		columns: [],
		distribution
	};
	meta.tables[INTERIOR_SLUG] = interior;
	payloads[interior.split] = encode(KIND_SPLIT, TOKEN, 12, [
		{ name: 'split', type: 'bits', values: new Array(12).fill(false) }
	]);
	payloads[`${INTERIOR_SLUG}/0/0.bin.gz`] = encode(
		KIND_TILE,
		TOKEN,
		2,
		columns(),
		tileInfoBytes(0, 0, 0)
	);
	const reads: string[] = [];
	return {
		reads,
		metadata: async () => meta,
		file: async (path) => {
			reads.push(path);
			const payload = payloads[path];
			if (!payload) throw new Error(`${path} returned 404`);
			return new Container(own(payload));
		},
		allowed: extrasolarAllowed
	};
}

afterEach(() => configureHost({}));

describe('the Interior table', () => {
	it('reads a fitted row, its values and its ranges', async () => {
		configureHost({ textures: 'site-only' });
		const interior = await fetchStarInterior(STAR, new ExtrasolarLookup(source('site-only')));
		expect(interior).toMatchObject({
			id: STAR,
			tier: 2,
			curated: null,
			stage: 'main_sequence',
			fehSource: 'pastel-2020',
			teffSource: 'flower-1996',
			luminositySource: 'radius',
			mass: { value: 2.25, range: [2, 2.5] },
			radius: { value: 1.75, range: [1.5, 2] },
			envelopeBaseRadius: { value: 0.5, range: [0.25, 0.75] },
			convectiveCoreMass: [0.25, 0.5],
			heliumCoreMass: null,
			centreTemperature: { value: 2.5e7, range: [2e7, 3e7] },
			centreDensity: { value: null, range: null },
			centreX: [0.125, 0.5],
			centreY: null
		});
	});

	it('reads the block of a curated row as it is', async () => {
		configureHost({ textures: 'site-only' });
		const interior = await fetchStarInterior(SECOND, new ExtrasolarLookup(source('site-only')));
		expect(interior?.tier).toBe(0);
		expect(interior?.curated).toEqual(CURATED);
	});

	it('has no row for a star that the table does not hold', async () => {
		configureHost({ textures: 'site-only' });
		const lookup = new ExtrasolarLookup(source('site-only'));
		expect(await fetchStarInterior(WITH_TABLE_2, lookup)).toBeNull();
	});

	it('is never fetched by a host below its tier, such as an embed', async () => {
		for (const textures of [undefined, 'non-commercial'] as const) {
			configureHost(textures ? { textures } : {});
			const files = source('site-only');
			expect(await fetchStarInterior(STAR, new ExtrasolarLookup(files))).toBeNull();
			expect(files.reads.filter((path) => path.startsWith(`${INTERIOR_SLUG}/`))).toEqual([]);
		}
	});

	it('is none where the export has no such table', async () => {
		configureHost({ textures: 'site-only' });
		const files = source('site-only');
		const meta = await files.metadata();
		delete meta!.tables[INTERIOR_SLUG];
		expect(await fetchStarInterior(STAR, new ExtrasolarLookup(files))).toBeNull();
	});
});
