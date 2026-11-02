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
import { jdToDate, utcToTdb } from '$lib/time/jd';
import { ObjectType } from '$lib/types/objects';

const SUN_GM = 132712440041.94;
const EARTH_MOON_GM = 403503.2355;
const JOVIAN_SYSTEM_GM = 126712764.1;

vi.mock('$lib/fetch/systems-global', () => ({
	getGmKm3s2: (naif: number) =>
		naif === 0 || naif === 10
			? SUN_GM
			: naif === 3
				? EARTH_MOON_GM
				: naif === 5
					? JOVIAN_SYSTEM_GM
					: undefined
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
// Records are dated in TDB; JD and LATER are the clock's UTC.
const FIRST = chunk(utcToTdb(JD), NEAR_KM);
const SECOND = chunk(utcToTdb(LATER), FAR_KM);
const withoutEarth = (records: ChebyshevBody[]) => records.filter((r) => r.naifId !== 399);

/** The bodies as the loader builds them at `JD`, over a store that answers each
 *  date with the records of the chunk that covers it. */
function loaded(records: ChebyshevBody[]) {
	const covers = (r: ChebyshevBody, jd: number) => r.startJds[0] <= jd && jd < r.endJds[0];
	const store = {
		bodiesAt: (jd: number) =>
			records
				.filter((r) => covers(r, jd))
				.map((body) => ({ zone: 'major', body, startJd: body.startJds[0], endJd: body.endJds[0] })),
		body: (id: string, jd: number) => records.find((r) => r.id === id && covers(r, jd)) ?? null
	} as unknown as ChebyshevStore;
	return new ChunkLoader(store).processChebyshev(jdToDate(JD), new Map());
}

function moonOver(records: ChebyshevBody[]) {
	return loaded(records).find((b) => b.data.id === 'naif-301')!;
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
		expect(later.epoch).toBe(utcToTdb(LATER));
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

describe('ChunkLoader.processChebyshev, a planet about the Sun', () => {
	const MID = utcToTdb(JD);
	const R_KM = 5.2 * AU_KM;
	const SUM_GM = SUN_GM + JOVIAN_SYSTEM_GM;
	/** A barycentre `naif` on a circle under `gm`, with the Sun at the origin of the file. */
	const onCircle = (naif: number, gm: number) => [
		record(10, 0, ObjectType.STAR, MID, 0, 0),
		record(naif, 0, ObjectType.BARYCENTER, MID, R_KM, Math.sqrt(gm / R_KM) * DAY_S)
	];
	const body = (naif: number, gm: number) =>
		loaded(onCircle(naif, gm)).find((b) => b.data.id === `naif-${naif}`)!.data;

	it('fits the Sun-centred orbit with the GM of the Sun plus the GM of its system', () => {
		const { helioElements } = body(5, SUM_GM);
		expect(helioElements!.a).toBeCloseTo(5.2, 9);
		expect(helioElements!.e).toBeLessThan(1e-9);
		const motion = Math.sqrt(SUM_GM / R_KM ** 3) * DAY_S * (180 / Math.PI);
		expect(helioElements!.n / motion).toBeCloseTo(1, 9);
	});

	it('keeps the GM of the Sun alone for the ellipse that the map redraws', () => {
		const { a } = body(5, SUM_GM);
		expect(a / 5.2).toBeCloseTo(1 / (2 - SUM_GM / SUN_GM), 9);
	});

	it('takes the GM of the Sun alone for a body with no GM', () => {
		expect(body(7, SUN_GM).helioElements!.a).toBeCloseTo(5.2, 9);
	});
});
