import { describe, expect, it } from 'vitest';
import { Container } from '$lib/fetch/extrasolar/container';
import { TableRow, type ExtrasolarRecord, type StarRadius } from '$lib/fetch/extrasolar/lookup';
import type { ExtrasolarTable } from '$lib/fetch/extrasolar/files';
import { encode } from '$lib/fetch/extrasolar/__fixtures__/writer';
import { pointSourceRecord, tableRow } from '$lib/fetch/extrasolar/__fixtures__/record';
import { makeStarBody } from './star-focus';

/** A star whose Metadata row has `radius`, with Point source columns `extra`. */
function record(
	radius: StarRadius | null,
	extra: Record<string, number | null> = {},
	cls = 'star'
): ExtrasolarRecord {
	const values: Record<string, number | null> = {
		ra: 45,
		dec: 30,
		parallax: 100,
		parallax_error: 1,
		teff_gspphot: 3000,
		phot_bp_mean_mag: 8,
		phot_rp_mean_mag: 5,
		...extra
	};
	const bytes = encode(
		1,
		'test',
		1,
		Object.entries(values).map(([name, value]) => ({ name, type: 'float32', values: [value] }))
	);
	const row = new TableRow(
		'point-source',
		{} as ExtrasolarTable,
		new Container(bytes.buffer as ArrayBuffer),
		0
	);
	return {
		id: 22137869,
		metadata: { name: 'Test star', class: cls, radius } as ExtrasolarRecord['metadata'],
		home: 'point-source',
		rows: new Map([['point-source', row]]),
		credits: []
	};
}

describe('a focused binary star', () => {
	const star = [
		{ name: 'ra', type: 'float64' as const, values: [45] },
		{ name: 'dec', type: 'float64' as const, values: [30] },
		{ name: 'parallax', type: 'float32' as const, values: [10] },
		{ name: 'parallax_error', type: 'float32' as const, values: [0.125] },
		{ name: 'phot_g_mean_mag', type: 'float32' as const, values: [8] }
	];
	const orbit = (type: string) => [
		{ name: 'nss_solution_type', type: 'dict' as const, values: [type] },
		{ name: 'parallax_nss', type: 'float32' as const, values: [12.5] },
		{ name: 'parallax_nss_error', type: 'float32' as const, values: [0.0625] }
	];
	const distance = (tree: number[] | null | undefined) => Math.hypot(...(tree ?? [NaN]));

	it('is placed and graded by the parallax of an astrometric orbit solution', () => {
		const body = makeStarBody(pointSourceRecord(star, [], orbit('AstroSpectroSB1')));
		expect(distance(body.extrasolar?.tree)).toBeCloseTo(80, 9);
		expect(body.extrasolar?.absMag).toBeCloseTo(8 + 5 * Math.log10(12.5) - 10, 2);
	});

	it('keeps the single-star parallax beside an eclipsing solution', () => {
		const body = makeStarBody(pointSourceRecord(star, [], orbit('EclipsingBinary')));
		expect(distance(body.extrasolar?.tree)).toBeCloseTo(100, 9);
		expect(body.extrasolar?.absMag).toBeCloseTo(8 + 5 * Math.log10(10) - 10, 2);
	});
});

describe('a focused object with no point', () => {
	/** A node or a held star at the place of its System row. */
	function pointless(cls: string, radius: StarRadius | null): ExtrasolarRecord {
		const row = tableRow('system', 3, [
			{ name: 'ra', type: 'float64', values: [45] },
			{ name: 'dec', type: 'float64', values: [30] },
			{ name: 'distance', type: 'float64', values: [10] }
		]);
		return {
			id: 7,
			metadata: { name: 'Pair', class: cls, radius } as ExtrasolarRecord['metadata'],
			rows: new Map([['system', row]]),
			home: 'system',
			credits: []
		};
	}

	it('has the place of its System row, and no tree place or light', () => {
		const body = makeStarBody(pointless('binary star', null));
		expect(body.extrasolar?.scene).not.toBeNull();
		expect(body.extrasolar?.tree).toBeNull();
		expect(body.extrasolar?.absMag).toBeNull();
	});

	it('gives a held star no sphere to frame, though its Metadata row has a radius', () => {
		const body = makeStarBody(pointless('star', { solar: 1.2, source: 'literature' }));
		expect(body.data.radiusKm).toBeNaN();
		expect(body.extrasolar?.radiusKm).toBeNull();
	});
});

describe('a focused stellar photosphere', () => {
	const flameSpec = { solar: 2, source: 'gaia-dr3-flame-spec' } as const;

	it('converts the Metadata radius to km for both the camera and renderer', () => {
		const body = makeStarBody(record(flameSpec));
		expect(body.data.radiusKm).toBe(1_391_400);
		expect(body.extrasolar?.radiusKm).toBe(body.data.radiusKm);
		expect(body.extrasolar?.teff).toBe(3000);
		expect(body.extrasolar?.colour).toBe(3);
		expect(body.extrasolar?.scene).not.toBeNull();
	});

	it('reads no Point source radius', () => {
		const columns = { radius_flame: 3, radius_gspphot: 1, host_radius: 0.65 };
		expect(makeStarBody(record(flameSpec, columns)).data.radiusKm).toBe(1_391_400);
	});

	it('draws a point where the Metadata row has no radius', () => {
		const body = makeStarBody(record(null, { radius_flame: 3, host_radius: 0.65 }, 'binary star'));
		expect(body.data.radiusKm).toBeNaN();
		expect(body.extrasolar?.radiusKm).toBeNull();
		expect(body.extrasolar?.scene).not.toBeNull();
	});
});
