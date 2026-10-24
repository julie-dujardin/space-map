import { describe, expect, it } from 'vitest';
import { Container } from '$lib/fetch/extrasolar/container';
import { TableRow, type ExtrasolarRecord } from '$lib/fetch/extrasolar/lookup';
import type { ExtrasolarTable } from '$lib/fetch/extrasolar/files';
import { encode } from '$lib/fetch/extrasolar/__fixtures__/writer';
import { makeStarBody } from './star-focus';

function record(radius: number | null | undefined): ExtrasolarRecord {
	const values: Record<string, number | null> = {
		ra: 45,
		dec: 30,
		parallax: 100,
		parallax_error: 1,
		teff_gspphot: 3000,
		phot_bp_mean_mag: 8,
		phot_rp_mean_mag: 5
	};
	if (radius !== undefined) values.radius_gspphot = radius;
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
		metadata: { name: 'Test star' } as ExtrasolarRecord['metadata'],
		home: 'point-source',
		rows: new Map([['point-source', row]]),
		credits: []
	};
}

describe('a focused stellar photosphere', () => {
	it('converts solar radii to km for both the camera and renderer', () => {
		const body = makeStarBody(record(2));
		expect(body.data.radiusKm).toBe(1_391_400);
		expect(body.extrasolar?.radiusKm).toBe(body.data.radiusKm);
		expect(body.extrasolar?.teff).toBe(3000);
		expect(body.extrasolar?.colour).toBe(3);
		expect(body.extrasolar?.scene).not.toBeNull();
	});

	it.each([undefined, null, 0, -1, NaN, Infinity])(
		'preserves an unknown radius (%s), including older exports',
		(radius) => {
			const body = makeStarBody(record(radius));
			expect(body.data.radiusKm).toBeNaN();
			expect(body.extrasolar?.radiusKm).toBeNull();
		}
	);
});
