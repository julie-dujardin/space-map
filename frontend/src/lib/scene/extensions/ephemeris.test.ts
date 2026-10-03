import { describe, expect, it, vi } from 'vitest';
import type { ObjectDetailData } from '$lib/fetch/objects/object-data';
import { dateToJD } from '$lib/time/jd';
import { distanceKm, offsetKm, subsolarPoint } from './ephemeris';

const AU_KM = 149597870.7;
const DATE = new Date('1971-07-31T13:00:00Z');

/** A circular orbit in the ecliptic, `ma` degrees along it at {@link DATE}. */
function orbit(parent: string, a: number, ma: number, diameter?: number) {
	return {
		type: 'asteroid',
		sbdb: diameter ? { diameter } : undefined,
		orbit: { parent_id: parent, a, e: 0, i: 0, om: 0, w: 0, ma, n: 1, epoch_jd: dateToJD(DATE) }
	};
}

const CATALOGUE: Record<string, object> = {
	'naif-10': orbit('naif-0', 0, 0),
	near: orbit('naif-0', 1, 0, 2000),
	far: orbit('naif-0', 2, 180),
	moon: orbit('near', 0.001, 90),
	orphan: orbit('nothing', 1, 0),
	loop: orbit('loop', 1, 0)
};

vi.mock('$lib/fetch/metadata', async (original) => ({
	...(await original<typeof import('$lib/fetch/metadata')>()),
	fetchMetadata: () => Promise.resolve({ position: { zones: {} } })
}));
vi.mock('$lib/fetch/systems-global', async (original) => ({
	...(await original<typeof import('$lib/fetch/systems-global')>()),
	loadSystemsGlobal: () => Promise.resolve()
}));
vi.mock('$lib/fetch/objects/object-data', async (original) => ({
	...(await original<typeof import('$lib/fetch/objects/object-data')>()),
	fetchObjectDetail: (id: string) =>
		Promise.resolve({ global: CATALOGUE[id] ?? null, localized: null } as ObjectDetailData)
}));

describe('distanceKm', () => {
	it('measures between two bodies at the date', async () => {
		expect(await distanceKm({ body: 'near' }, { body: 'far' }, DATE)).toBeCloseTo(3 * AU_KM, 0);
	});

	it('moves a body along its orbit to another date', async () => {
		// A quarter of a turn on, at one degree a day.
		const later = new Date(DATE.getTime() + 90 * 86400000);
		const offset = (await offsetKm({ body: 'naif-10' }, { body: 'near' }, later))!;
		expect(offset[0]).toBeCloseTo(0, 0);
		expect(offset[1]).toBeCloseTo(AU_KM, 0);
	});

	it('places a moon from its parent', async () => {
		const km = await distanceKm({ body: 'near' }, { body: 'moon' }, DATE);
		expect(km).toBeCloseTo(0.001 * AU_KM, 0);
	});

	it('measures from a place on a surface', async () => {
		const pole = { body: 'near', latitude: 90, longitude: 0 };
		expect(await distanceKm(pole, { body: 'near' }, DATE)).toBeCloseTo(1000, 6);
	});

	it('is null for a body the export does not have', async () => {
		expect(await distanceKm({ body: 'near' }, { body: 'unknown' }, DATE)).toBeNull();
	});

	it('is null for a body whose parent is nowhere', async () => {
		expect(await distanceKm({ body: 'near' }, { body: 'orphan' }, DATE)).toBeNull();
		expect(await distanceKm({ body: 'near' }, { body: 'loop' }, DATE)).toBeNull();
	});

	it('answers each of several reads asked at once for its own date', async () => {
		const later = new Date(DATE.getTime() + 180 * 86400000);
		const [now, then] = await Promise.all([
			distanceKm({ body: 'near' }, { body: 'far' }, DATE),
			distanceKm({ body: 'naif-10' }, { body: 'near' }, later)
		]);
		expect(now).toBeCloseTo(3 * AU_KM, 0);
		expect(then).toBeCloseTo(AU_KM, 0);
	});
});

describe('subsolarPoint', () => {
	it('is the place that faces the Sun', async () => {
		const noon = (await subsolarPoint('near', DATE))!;
		expect(noon.lat).toBeCloseTo(0, 6);
		expect(Math.abs(noon.lon)).toBeCloseTo(180, 6);
	});

	it('is null for the Sun', async () => {
		expect(await subsolarPoint('naif-10', DATE)).toBeNull();
	});
});
