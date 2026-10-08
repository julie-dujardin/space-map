import { describe, expect, it, vi } from 'vitest';
import type { ObjectDetailData } from '$lib/fetch/objects/object-data';
import { dateToJD } from '$lib/time/jd';
import { distanceKm, offsetKm, subsolarPoint, sunlight } from './ephemeris';

const AU_KM = 149597870.7;
const DATE = new Date('1971-07-31T13:00:00Z');

/** A circular orbit in the ecliptic, `ma` degrees along it at {@link DATE}. */
function orbit(parent: string, a: number, ma: number, diameter?: number) {
	return {
		type: 'asteroid',
		sbdb: diameter ? { diameter } : undefined,
		coverage: { windows: [[null, null]] },
		orbit: { parent_id: parent, a, e: 0, i: 0, om: 0, w: 0, ma, n: 1, epoch_jd: dateToJD(DATE) }
	};
}

/** The orbit of the moons of `near` that are near its shadow, in AU. */
const CLOSE = 0.0001;
/** Degrees round that orbit from the axis of the shadow to its edge. */
const EDGE = (Math.asin(1000 / (CLOSE * AU_KM)) * 180) / Math.PI;

const CATALOGUE: Record<string, object> = {
	'naif-10': orbit('naif-0', 0, 0, 1391400),
	near: orbit('naif-0', 1, 0, 2000),
	far: orbit('naif-0', 2, 180),
	moon: orbit('near', 0.001, 90),
	shaded: orbit('near', CLOSE, 0, 200),
	sunward: orbit('near', CLOSE, 180, 200),
	edge: orbit('near', CLOSE, EDGE),
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

describe('sunlight', () => {
	it('is 1 for a body with nothing between it and the Sun', async () => {
		expect(await sunlight('near', DATE)).toBe(1);
		expect(await sunlight('sunward', DATE)).toBe(1);
		expect(await sunlight('moon', DATE)).toBe(1);
	});

	it('is 0 in the shadow of the body it orbits', async () => {
		expect(await sunlight('shaded', DATE)).toBe(0);
	});

	it('is a half for a point on the edge of that shadow', async () => {
		expect(await sunlight('edge', DATE)).toBeCloseTo(0.5, 2);
	});

	it('is null for the Sun, and for a body that is nowhere', async () => {
		expect(await sunlight('naif-10', DATE)).toBeNull();
		expect(await sunlight('unknown', DATE)).toBeNull();
		expect(await sunlight('orphan', DATE)).toBeNull();
	});
});
