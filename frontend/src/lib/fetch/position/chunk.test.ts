/**
 * The curve of a moon is drawn on its planet, so its elements are about its
 * planet. The ephemeris gives both about the barycentre of their system, in
 * records that each cover one chunk.
 */

import { describe, expect, it, vi } from 'vitest';
import type { ChebyshevBody } from '$lib/fetch/position/chebyshev/parse';
import type { ChebyshevStore } from '$lib/fetch/position/chebyshev/store';
import { orbitalElementsToPositionJD } from '$lib/math/orbit/position';
import { AU_KM, kmToScene } from '$lib/math/units';
import { jdToDate } from '$lib/time/jd';
import { ObjectType } from '$lib/types/objects';

const SUN_GM = 132712440041.94;
const EARTH_MOON_GM = 403503.2355;

vi.mock('$lib/fetch/systems-global', () => ({
	getGmKm3s2: (naif: number) => (naif === 0 ? SUN_GM : naif === 3 ? EARTH_MOON_GM : undefined)
}));

const { ChunkLoader } = await import('./chunk');

const JD = 2461300;
const DAY_S = 86400;
/** Each chunk is two days long. The second one starts where the first ends. */
const LATER = JD + 2;
/** The share of the Earth-Moon line that Earth is off the barycentre. */
const EARTH_SHARE = 1 / 82.3;

/** A record on a straight line over the two days about `midJd`: in the middle
 *  it is at `x` km and moves along y. */
function record(
	naifId: number,
	parentId: number,
	objectType: ObjectType,
	midJd: number,
	x: number,
	vy: number
): ChebyshevBody {
	return {
		id: `naif-${naifId}`,
		naifId,
		parentId,
		hasLocalized: false,
		objectType,
		radiusKm: NaN,
		visibleFromDays: NaN,
		coeffsPerAxis: 2,
		startJds: Float64Array.of(midJd - 1),
		endJds: Float64Array.of(midJd + 1),
		// Over two days the second coefficient is the speed per day.
		coeffs: Float64Array.of(x, 0, 0, vy, 0, 0)
	};
}

/** One chunk of the Earth system: the Moon on a circle, `separationKm` from Earth. */
function chunk(midJd: number, separationKm: number): ChebyshevBody[] {
	const speed = Math.sqrt(EARTH_MOON_GM / separationKm) * DAY_S;
	return [
		record(3, 0, ObjectType.BARYCENTER, midJd, AU_KM, Math.sqrt(SUN_GM / AU_KM) * DAY_S),
		record(399, 3, ObjectType.PLANET, midJd, -separationKm * EARTH_SHARE, -speed * EARTH_SHARE),
		record(
			301,
			3,
			ObjectType.MOON,
			midJd,
			separationKm * (1 - EARTH_SHARE),
			speed * (1 - EARTH_SHARE)
		)
	];
}

const NEAR_KM = 384400;
const FAR_KM = 400000;
const FIRST = chunk(JD, NEAR_KM);
const SECOND = chunk(LATER, FAR_KM);
const withoutEarth = (records: ChebyshevBody[]) => records.filter((r) => r.naifId !== 399);

/** The Moon as the loader builds it at `JD`, over a store that answers each
 *  date with the records of the chunk that covers it. */
function moonOver(records: ChebyshevBody[]) {
	const covers = (r: ChebyshevBody, jd: number) => r.startJds[0] <= jd && jd < r.endJds[0];
	const store = {
		bodiesAt: (jd: number) =>
			records
				.filter((r) => covers(r, jd))
				.map((body) => ({ zone: 'major', body, startJd: body.startJds[0], endJd: body.endJds[0] })),
		body: (id: string, jd: number) => records.find((r) => r.id === id && covers(r, jd)) ?? null
	} as unknown as ChebyshevStore;
	const bodies = new ChunkLoader(store).processChebyshev(jdToDate(JD), new Map());
	return bodies.find((b) => b.data.id === 'naif-301')!;
}

describe('ChunkLoader.processChebyshev, a moon', () => {
	it('has its curve on its planet', () => {
		expect(moonOver(FIRST).orbitCenterId).toBe('naif-399');
	});

	it('has elements about its planet', () => {
		// About the barycentre the same state gives 366,500 km.
		expect(moonOver(FIRST).orbitElements!.a * AU_KM).toBeCloseTo(NEAR_KM, 0);
	});

	it('is on its curve', () => {
		const fromEarth = orbitalElementsToPositionJD(moonOver(FIRST).orbitElements!, JD)!;
		expect(fromEarth[0]).toBeCloseTo(kmToScene(NEAR_KM), 9);
		expect(fromEarth[1]).toBeCloseTo(0, 9);
		expect(fromEarth[2]).toBeCloseTo(0, 9);
	});

	it('takes later elements from the records of the later date', () => {
		const later = moonOver([...FIRST, ...SECOND]).rederiveElements!(LATER)!;
		expect(later.epoch).toBe(LATER);
		expect(later.a * AU_KM).toBeCloseTo(FAR_KM, 0);
		expect(orbitalElementsToPositionJD(later, LATER)![0]).toBeCloseTo(kmToScene(FAR_KM), 9);
	});

	it('has no elements when its planet has no record', () => {
		const moon = moonOver(withoutEarth(FIRST));
		expect(moon.orbitCenterId).toBe('naif-399');
		expect(moon.orbitElements).toBeUndefined();
		expect(moon.rederiveElements!(JD)).toBeNull();
	});

	it('has no later elements while the record of its planet for that date is not there', () => {
		const moon = moonOver([...FIRST, ...withoutEarth(SECOND)]);
		expect(moon.orbitElements).toBeDefined();
		expect(moon.rederiveElements!(LATER)).toBeNull();
	});
});
