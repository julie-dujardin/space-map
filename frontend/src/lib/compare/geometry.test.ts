import { afterEach, describe, expect, it, vi } from 'vitest';
import { ExtrasolarLookup, extrasolarLookup, type StarRadius } from '$lib/fetch/extrasolar/lookup';
import {
	pointSourceRecord,
	systemRow,
	valueColumns
} from '$lib/fetch/extrasolar/__fixtures__/record';
import { own } from '$lib/fetch/extrasolar/__fixtures__/export';
import { BINARY, HELD, STAR, syntheticExport } from '$lib/fetch/extrasolar/__fixtures__/synthetic';
import { Container } from '$lib/fetch/extrasolar/container';
import { SOLAR_RADIUS_KM } from '$lib/math/units';
import { resolveObject, sizeText, type CompareObject } from './geometry';

afterEach(() => vi.restoreAllMocks());

/** The size the list, the labels and the fit give an object. */

const object = (geometry: CompareObject['geometry'], radiusKm = 6525): CompareObject => ({
	id: 'x-27424668-b-1',
	name: 'Proxima Cen b',
	radiusKm,
	geometry
});

describe('sizeText', () => {
	it('marks an estimated size', () => {
		expect(sizeText(object({ sizeEstimated: true }))).toBe('≈ 13,050 km');
	});

	it('gives a measured size as it stands', () => {
		expect(sizeText(object({}))).toBe('13,050 km');
	});

	it('gives a craft across its whole mesh', () => {
		expect(sizeText(object({ meshSpanRatio: 2 }, 0.01))).toBe('40 m');
	});
});

/** A star whose Point source row has radii the export passed over. */
function star(radius: StarRadius | null) {
	const columns = valueColumns({ teff: 5000, radius_literature: 3, radius_flame: 2 });
	return pointSourceRecord(columns, [], undefined, radius);
}

describe('a star in the comparison', () => {
	it('is drawn at its Metadata radius', async () => {
		const record = star({ solar: 0.75, source: 'nasa-exoplanet-archive' });
		vi.spyOn(extrasolarLookup, 'live').mockResolvedValue({ kind: 'live', record });
		const object = await resolveObject(`x-${STAR}`, { name: 'HD 189733' });
		expect(object?.radiusKm).toBe(Number((0.75 * SOLAR_RADIUS_KM).toPrecision(3)));
		expect(object?.geometry.photosphere).toEqual({ teff: 5000 });
	});

	it('is left out with no radius', async () => {
		vi.spyOn(extrasolarLookup, 'live').mockResolvedValue({ kind: 'live', record: star(null) });
		expect(await resolveObject(`x-${STAR}`, { name: 'A point' })).toBeNull();
	});

	it("stands for its primary's radius where it is a star system", async () => {
		const primary = { ...star({ solar: 2, source: 'gaia-dr3-flame-spec' }), id: STAR + 1 };
		const node = star(null);
		node.rows = new Map([['system', systemRow(primary.id)]]);
		node.home = 'system';
		vi.spyOn(extrasolarLookup, 'live').mockImplementation(async (id) => ({
			kind: 'live',
			record: Number(id) === primary.id ? primary : node
		}));
		const object = await resolveObject(`x-${STAR}`, { name: 'A pair' });
		expect(object?.radiusKm).toBe(Number((2 * SOLAR_RADIUS_KM).toPrecision(3)));
	});

	/** The synthetic export, where the held star HELD, first in the point
	 *  BINARY, has `radius` if given and is `dominant` there. */
	function synthetic(radius?: StarRadius, dominant = true) {
		const { meta, payloads } = syntheticExport({ dominant });
		const files = new Map(
			Object.entries(payloads).map(([path, bytes]) => [path, new Container(own(bytes))])
		);
		const lookup = new ExtrasolarLookup({
			metadata: async () => meta,
			file: async (path) => files.get(path)!,
			allowed: () => true
		});
		vi.spyOn(extrasolarLookup, 'live').mockImplementation(async (id) => {
			const found = await lookup.live(id);
			if (found.kind !== 'live' || found.record.id !== HELD || !radius) return found;
			return {
				...found,
				record: { ...found.record, metadata: { ...found.record.metadata, radius } }
			};
		});
	}

	it("is a held star at its Metadata radius, in the colour of its System row's Teff", async () => {
		synthetic();
		const object = await resolveObject(`x-${HELD}`, { name: 'Test System Aa' });
		expect(object?.radiusKm).toBe(Number((0.75 * SOLAR_RADIUS_KM).toPrecision(3)));
		expect(object?.geometry.photosphere).toEqual({ teff: 4500 });
	});

	it('stands for a point of several stars by its dominant first member', async () => {
		synthetic({ solar: 2, source: 'jmdc' });
		const object = await resolveObject(`x-${BINARY}`, { name: 'A point' });
		expect(object?.radiusKm).toBe(Number((2 * SOLAR_RADIUS_KM).toPrecision(3)));
		expect(object?.geometry.photosphere).toEqual({ teff: 4500 });
	});

	it("sizes a point by its dominant member's own radius too", async () => {
		synthetic();
		const object = await resolveObject(`x-${BINARY}`, { name: 'A point' });
		expect(object?.radiusKm).toBe(Number((0.75 * SOLAR_RADIUS_KM).toPrecision(3)));
	});

	it('leaves out a point whose first member does not dominate it', async () => {
		synthetic({ solar: 2, source: 'jmdc' }, false);
		expect(await resolveObject(`x-${BINARY}`, { name: 'A point' })).toBeNull();
	});
});
