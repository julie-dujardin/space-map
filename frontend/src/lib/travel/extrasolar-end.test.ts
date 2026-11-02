import { afterEach, describe, expect, it, vi } from 'vitest';
import { HAS_EXPORT, diskSource } from '$lib/fetch/extrasolar/__fixtures__/export';
import {
	ExtrasolarLookup,
	extrasolarLookup,
	type ExtrasolarRecord
} from '$lib/fetch/extrasolar/lookup';
import { PlanetIndex, planetCatalogue, type PlanetSystem } from '$lib/fetch/extrasolar/planets';
import {
	pointSourceRecord,
	resolvedSystemRecord,
	systemRow
} from '$lib/fetch/extrasolar/__fixtures__/record';
import type { ColumnSpec } from '$lib/fetch/extrasolar/__fixtures__/writer';
import { elementsOffset } from '$lib/math/orbit/offset';
import {
	GM_SUN_KM3_S2,
	buildInterstellarCruiseRoute,
	buildInterstellarTorchRoute,
	eclipticToScene,
	endPlaceKm,
	norm,
	sub,
	type Route,
	type Vec3
} from '$lib/math/travel';
import { heldLine } from '$lib/math/travel/interstellar';
import { AU_KM, SOLAR_RADIUS_KM } from '$lib/math/units';
import { hostScene, makePlanetBodies } from '$lib/scene/exoplanets/bodies';
import {
	ALPHA_CEN,
	INDEX,
	elements,
	host,
	planet
} from '$lib/scene/exoplanets/__fixtures__/system';
import { sceneToEcliptic } from '$lib/scene/extensions/camera';
import { makeStarBody } from '$lib/scene/focus/star-focus';
import { PC_AU } from '$lib/scene/starfield/tree';
import type { PositionedBody } from '$lib/types/objects';
import {
	extrasolarEndOf,
	extrasolarTravelBody,
	massFromRadiusEarth,
	radiusFromMassEarth,
	resolveExtrasolarEnd,
	systemEndOf
} from './extrasolar-end';
import { orbitChoices, orbitFacts, hasGround } from './orbits';

const PC_KM = PC_AU * AU_KM;
const TAU_CETI = 21238067;
const GM_JUPITER = 1.2668653e8;
const GM_EARTH = 3.986004e5;

/** A file of Tau Ceti, at 1, 2, 3 pc, with these planets. */
function system(planets: PlanetSystem['planets']): PlanetSystem {
	return {
		token: '0'.repeat(16),
		system: TAU_CETI,
		hosts: [host(TAU_CETI, [1, 2, 3, 4])],
		planets
	};
}

function planetBody(file: PlanetSystem, id: string): PositionedBody {
	return makePlanetBodies(file).find((b) => b.data.id === id)!;
}

/** A star 10 pc out with a FLAME mass of 0.8 solar masses. */
function starRecord(extra: ColumnSpec[] = []) {
	return pointSourceRecord([
		{ name: 'ra', type: 'float64', values: [26] },
		{ name: 'dec', type: 'float64', values: [-16] },
		{ name: 'parallax', type: 'float32', values: [100] },
		{ name: 'parallax_error', type: 'float32', values: [0.1] },
		{ name: 'mass_flame', type: 'float32', values: [0.8] },
		{ name: 'radius_flame', type: 'float32', values: [0.9] },
		...extra
	]);
}

afterEach(() => vi.restoreAllMocks());

const SOLAR_MASS_EARTH = GM_SUN_KM3_S2 / GM_EARTH;

describe('the mass–radius relation', () => {
	it('gives the Earth about its own radius, and runs on across each branch', () => {
		expect(radiusFromMassEarth(1)).toBeCloseTo(1.008, 3);
		for (const m of [2.04, 131.6, 0.08 * SOLAR_MASS_EARTH]) {
			expect(radiusFromMassEarth(m * 0.9999) / radiusFromMassEarth(m * 1.0001)).toBeCloseTo(1, 3);
		}
	});

	it('climbs at 0.881 on the Stellar branch, and gives the Sun about its own radius', () => {
		const m = SOLAR_MASS_EARTH;
		expect(radiusFromMassEarth(m) / radiusFromMassEarth(m / 2)).toBeCloseTo(2 ** 0.881, 9);
		const sun = (radiusFromMassEarth(m) * 6378.1) / 695_700;
		expect(sun).toBeGreaterThan(0.9);
		expect(sun).toBeLessThan(1.1);
	});

	it('inverts on the Terran and Neptunian branches', () => {
		for (const m of [0.3, 1, 5, 40])
			expect(massFromRadiusEarth(radiusFromMassEarth(m))).toBeCloseTo(m, 6);
	});

	it('holds a giant radius at the start of the Jovian branch', () => {
		expect(massFromRadiusEarth(25)).toBeCloseTo(131.6, 6);
	});
});

describe('a planet end', () => {
	const file = system([
		planet(TAU_CETI, 1, elements(0.05), { radius: 0.0913, star_mass: 0.9, star_radius: 0.8 }),
		planet(TAU_CETI, 2, elements(0.5), { mass: 1, mass_kind: 'minimum' }),
		planet(TAU_CETI, 3, elements(1), { mass: 0.002, radius: 0.08, star_mass: 1 }),
		planet(TAU_CETI, 4, null)
	]);

	it('sits at its host, in the system of its host', () => {
		const end = extrasolarEndOf(planetBody(file, 'x-21238067-b-1'))!;
		expect(end.systemId).toBe('x-21238067');
		expect(end.star.id).toBe('x-21238067');
		expect(norm(end.star.positionKm) / PC_KM).toBeCloseTo(Math.sqrt(14), 6);
		expect(end.planet?.elements.a).toBe(0.05);
	});

	it('has the star of the star end of its host, and its own fits where the host has no record', () => {
		const host = makeStarBody({ ...starRecord(), id: TAU_CETI });
		const star = extrasolarEndOf(host)!.star;
		expect(extrasolarEndOf(planetBody(file, 'x-21238067-b-1'), host)!.star).toEqual(star);
		const alone = extrasolarEndOf(planetBody(file, 'x-21238067-b-1'))!.star;
		expect(alone.muKm3S2! / GM_SUN_KM3_S2).toBeCloseTo(0.9, 6);
		expect(alone.radiusKm).toBeCloseTo(0.8 * 695_700, -1);
	});

	it('takes its mass from its radius when that is all there is, and is rock', () => {
		const end = extrasolarEndOf(planetBody(file, 'x-21238067-b-1'))!;
		const size = end.planet!.size!;
		expect(size.massBasis).toBe('forecast');
		expect(size.radiusBasis).toBe('measured');
		expect(size.muKm3S2 / GM_EARTH).toBeCloseTo(massFromRadiusEarth((0.0913 * 71492) / 6378.1), 6);
		expect(end.planet!.rocky).toBe(true);
	});

	it('takes μ from a minimum mass and its radius from the relation', () => {
		const end = extrasolarEndOf(planetBody(file, 'x-21238067-b-2'))!;
		const size = end.planet!.size!;
		expect(size.muKm3S2).toBeCloseTo(GM_JUPITER, 0);
		expect(size.massBasis).toBe('minimum');
		expect(size.radiusBasis).toBe('forecast');
		expect(end.planet!.rocky).toBe(false);
	});

	it('has no size with neither a mass nor a radius, and so no travel body', () => {
		const end = extrasolarEndOf(planetBody(file, 'x-21238067-b-4'))!;
		expect(end.planet!.size).toBeNull();
		expect(end.planet!.orbitKnown).toBe(false);
		expect(extrasolarTravelBody(end)).toBeNull();
	});

	it('has no place when its host has none', () => {
		const lost = { ...file, hosts: [{ ...file.hosts[0], position: null }] };
		expect(extrasolarEndOf(planetBody(lost, 'x-21238067-b-1'))).toBeNull();
	});

	it('is priced with its own μ, and lands only on rock', () => {
		const rock = extrasolarTravelBody(extrasolarEndOf(planetBody(file, 'x-21238067-b-3'))!)!;
		expect(rock.mu).toBeCloseTo(0.002 * GM_JUPITER, 0);
		expect(rock.muEstimated).toBe(false);
		expect(rock.parentId).toBe('x-21238067');
		expect(rock.hillKm).toBeGreaterThan(0);
		expect(hasGround(rock)).toBe(true);
		const end = extrasolarEndOf(planetBody(file, 'x-21238067-b-3'))!;
		const unknown = { ...end, star: { ...end.star, muKm3S2: null } };
		expect(extrasolarTravelBody(unknown)!.hillKm).toBeUndefined();
		expect(extrasolarTravelBody(unknown, GM_SUN_KM3_S2)!.hillKm).toBeCloseTo(rock.hillKm!, 0);

		const giant = extrasolarTravelBody(extrasolarEndOf(planetBody(file, 'x-21238067-b-2'))!)!;
		expect(giant.muEstimated).toBe(true);
		expect(hasGround(giant)).toBe(false);
		const facts = orbitFacts(planetBody(file, 'x-21238067-b-2').data, giant, null);
		const kinds = orbitChoices(giant, facts, 'target', {
			hasSurface: hasGround(giant),
			customAltKm: 500
		}).map((c) => c.kind);
		expect(kinds).not.toContain('surface');
		expect(kinds).toContain('low-orbit');
	});
});

describe('a star end', () => {
	it('sits where the map draws the star, with its FLAME mass', () => {
		const end = extrasolarEndOf(makeStarBody(starRecord()))!;
		expect(end.systemId).toBe('x-1');
		expect(end.planet).toBeNull();
		expect(norm(end.star.positionKm) / PC_KM).toBeCloseTo(10, 4);
		expect(end.star.muKm3S2! / GM_SUN_KM3_S2).toBeCloseTo(0.8, 6);
		expect(end.star.radiusKm).toBeCloseTo(0.9 * 695_700, -1);
	});

	it('has no place without a distance', () => {
		const far = pointSourceRecord([
			{ name: 'ra', type: 'float64', values: [26] },
			{ name: 'dec', type: 'float64', values: [-16] }
		]);
		expect(extrasolarEndOf(makeStarBody(far))).toBeNull();
	});

	it('is met, passed or orbited at will between two systems', () => {
		const body = makeStarBody(starRecord());
		const travel = extrasolarTravelBody(extrasolarEndOf(body)!)!;
		const facts = { ...orbitFacts(body.data, travel, null), crossing: true };
		const kinds = (role: 'origin' | 'target') =>
			orbitChoices(travel, facts, role, { hasSurface: false, customAltKm: 500 }).map((c) => c.kind);
		expect(kinds('target')).toEqual(['rendezvous', 'custom', 'flyby']);
		expect(kinds('origin')).toEqual(['rendezvous', 'custom']);
	});

	it('takes μ from the trip when its mass is unknown', () => {
		const end = extrasolarEndOf(makeStarBody(starRecord()))!;
		const unknown = { ...end, star: { ...end.star, muKm3S2: null } };
		expect(extrasolarTravelBody(unknown)!.mu).toBe(0);
		expect(extrasolarTravelBody(unknown, 3e10)!.mu).toBe(3e10);
	});

	describe('with no radius', () => {
		const end = extrasolarEndOf(makeStarBody(starRecord()))!;
		const noRadius = { ...end, star: { ...end.star, radiusKm: null } };

		it('takes the radius of its own μ from the relation', () => {
			const expected = radiusFromMassEarth(end.star.muKm3S2! / GM_EARTH) * 6378.1;
			expect(extrasolarTravelBody(noRadius)!.radiusKm).toBeCloseTo(expected, 6);
		});

		it('takes it from the μ of the trip when its mass is unknown', () => {
			const unknown = { ...noRadius, star: { ...noRadius.star, muKm3S2: null } };
			// AD Leo: 0.42 solar masses from its planet's period, 0.39 solar radii measured.
			const mu = 0.42 * GM_SUN_KM3_S2;
			const radius = extrasolarTravelBody(unknown, mu)!.radiusKm / 695_700;
			expect(radius).toBeGreaterThan(0.4);
			expect(radius).toBeLessThan(0.5);
		});

		it('keeps a catalogued radius over the forecast', () => {
			expect(extrasolarTravelBody(end, 0.1 * GM_SUN_KM3_S2)!.radiusKm).toBe(end.star.radiusKm);
		});

		it('stays a point with no μ, since no orbit is priced against it', () => {
			const unknown = { ...noRadius, star: { ...noRadius.star, muKm3S2: null } };
			const travel = extrasolarTravelBody(unknown)!;
			expect(travel).toMatchObject({ mu: 0, radiusKm: 1 });
			const facts = orbitFacts(end.body, travel, null);
			const kinds = orbitChoices(travel, facts, 'target', {
				hasSurface: false,
				customAltKm: 1000
			}).map((c) => c.kind);
			expect(kinds).toEqual(['rendezvous', 'flyby']);
		});
	});
});

describe('the end of a trip between two systems', () => {
	const WELL = { mu: GM_EARTH, radiusKm: 384_400 };

	it('keeps the wells of an end in the solar system, at the Sun', () => {
		const moon = {
			id: 'naif-301',
			mu: 4902.8,
			muEstimated: false,
			radiusKm: 1737.4,
			elements: { a: 1, e: 0, i: 0, om: 0, w: 0, ma: 0, n: 0.9856, epoch: 2451545 }
		};
		expect(systemEndOf(moon, null, [WELL])).toEqual({
			body: moon,
			starKm: [0, 0, 0],
			starMu: GM_SUN_KM3_S2,
			atStar: false,
			wells: [WELL]
		});
	});

	it('puts an end of another star in no well', () => {
		const end = extrasolarEndOf(makeStarBody(starRecord()))!;
		const star = systemEndOf(extrasolarTravelBody(end)!, end, [WELL]);
		expect(star.wells).toEqual([]);
		expect(star.atStar).toBe(true);
	});
});

describe('the place of an end on the map', () => {
	/** About 150 m. A place a parsec out holds no finer digits than this. */
	const SAME_PLACE = 1e-8;
	const HOST = ALPHA_CEN.hosts[0];
	const SIZE = { radius: 0.1, mass: 0.003 };
	const file = (el: ReturnType<typeof elements> | null): PlanetSystem => ({
		...ALPHA_CEN,
		hosts: [HOST],
		planets: [planet(HOST.id, 1, el, SIZE)]
	});

	/** The kernel's view of the planet of `system`, and the scene's body of it. */
	function kernelEnd(system: PlanetSystem) {
		const body = makePlanetBodies(system)[0];
		const end = extrasolarEndOf(body)!;
		return { body, end: systemEndOf(extrasolarTravelBody(end)!, end, []) };
	}

	/** Where the scene draws `body` at `jd`: the place of its host and its offset. */
	function drawn(body: PositionedBody, jd: number): Vec3 {
		const [x, y, z] = hostScene(HOST)!;
		const [dx, dy, dz] = elementsOffset(body.data, jd) as Vec3;
		return [x + dx, y + dy, z + dz];
	}

	const expectSamePlace = (at: Vec3, scene: Vec3) =>
		expect(norm(sub(eclipticToScene(at), scene))).toBeLessThan(SAME_PLACE);

	it('is where the scene draws a planet with an orbit', () => {
		const { body, end } = kernelEnd(file(elements(0.0485, { e: 0.3, i: 70, om: 200, w: 120 })));
		for (const jd of [2400000, 2451545, 2460000, 2500000, 3e7]) {
			expectSamePlace(endPlaceKm(end, jd), drawn(body, jd));
		}
	});

	it('is where the scene holds a planet with an orbit and no period', () => {
		const { body, end } = kernelEnd(file(elements(2, { e: 0.3, n: 0 })));
		for (const jd of [2451545, 2460000, 3e7]) {
			expectSamePlace(endPlaceKm(end, jd), drawn(body, jd));
		}
	});

	it('is where the scene holds a planet with no published orbit', () => {
		const { body, end } = kernelEnd(file(null));
		expect(extrasolarEndOf(body)!.planet!.orbitKnown).toBe(false);
		expectSamePlace(endPlaceKm(end, 2460000), drawn(body, 2460000));
		// With no mass for the host, the place is the same.
		const unknown = { ...end, starMu: undefined };
		expectSamePlace(endPlaceKm(unknown, 2460000), drawn(body, 2460000));
	});

	it.each([
		['a known mass', GM_SUN_KM3_S2],
		['no known mass', undefined]
	])('flies to and from a planet with no published orbit, its star of %s', (_, starMu) => {
		const { end } = kernelEnd(file(null));
		const lone = { ...end, starMu };
		const home = systemEndOf(
			{
				id: 'naif-399',
				mu: GM_EARTH,
				muEstimated: false,
				radiusKm: 6378,
				elements: { a: 1, e: 0, i: 0, om: 0, w: 0, ma: 0, n: 0.9856, epoch: 2451545 }
			},
			null,
			[]
		);
		const options = { departureMode: 'orbit', arrivalMode: 'low-orbit' } as const;
		const drive = { kind: 'budget', dvKms: 80 } as const;
		for (const [from, to] of [
			[home, lone],
			[lone, home]
		]) {
			const held = buildInterstellarTorchRoute(from, to, 2460000, 9.8, options)!;
			expect(held.interstellar!.distanceKm).toBeGreaterThan(0);
			const coast = buildInterstellarCruiseRoute(from, to, 2460000, drive, {
				...options,
				launchWindow: true
			}) as Route;
			expect(coast.tofDays).toBeGreaterThan(0);
		}
	});
});

describe('resolving an end from the export', () => {
	it('reads a planet through the planet files, as its live body', async () => {
		vi.spyOn(planetCatalogue, 'planet').mockResolvedValue({
			planet: ALPHA_CEN.planets[0],
			system: ALPHA_CEN
		});
		vi.spyOn(extrasolarLookup, 'live').mockResolvedValue({ kind: 'missing', reason: 'no-row' });
		const end = await resolveExtrasolarEnd('x-27424668-b-1');
		expect(end?.body.id).toBe('x-27424668-b-1');
		expect(end?.systemId).toBe('x-27424668');
		// With no place of its own, the host is where the system file puts it.
		const file = extrasolarEndOf(planetBody(ALPHA_CEN, 'x-27424668-b-1'))!;
		expect(end?.star.positionKm).toEqual(file.star.positionKm);
	});

	it('puts the star of a planet where the scene draws its host', async () => {
		vi.spyOn(planetCatalogue, 'planet').mockResolvedValue({
			planet: ALPHA_CEN.planets[0],
			system: ALPHA_CEN
		});
		const record = { ...starRecord(), id: 27424668 };
		vi.spyOn(extrasolarLookup, 'live').mockResolvedValue({ kind: 'live', record });
		vi.spyOn(planetCatalogue, 'index').mockResolvedValue(null);
		const end = await resolveExtrasolarEnd('x-27424668-b-1');
		const drawn = makeStarBody(record).extrasolar!.scene!;
		expect(end?.star.positionKm).toEqual(sceneToEcliptic(drawn));
	});

	it('reads a star through the lookup', async () => {
		vi.spyOn(extrasolarLookup, 'live').mockResolvedValue({ kind: 'live', record: starRecord() });
		vi.spyOn(planetCatalogue, 'index').mockResolvedValue(null);
		const end = await resolveExtrasolarEnd('x-1');
		expect(end?.body.id).toBe('x-1');
		expect(end?.star.muKm3S2).not.toBeNull();
	});

	it('places a host with no distance of its own where the planet index puts it', async () => {
		const placeless = { ...starRecord(), id: 27424668 };
		placeless.rows = new Map();
		vi.spyOn(extrasolarLookup, 'live').mockResolvedValue({ kind: 'live', record: placeless });
		vi.spyOn(planetCatalogue, 'index').mockResolvedValue(new PlanetIndex(INDEX));
		const end = await resolveExtrasolarEnd('x-27424668');
		expect(norm(end!.star.positionKm) / PC_KM).toBeCloseTo(Math.hypot(-0.47, -0.36, -1.16), 6);
	});

	it('goes to the primary star of a star system', async () => {
		const SYSTEM = 597894079;
		const PRIMARY = 27468735;
		const records = new Map<number, ExtrasolarRecord>([
			[SYSTEM, resolvedSystemRecord(SYSTEM, PRIMARY)],
			[PRIMARY, { ...starRecord(), id: PRIMARY }],
			[9, resolvedSystemRecord(9, null)]
		]);
		vi.spyOn(extrasolarLookup, 'live').mockImplementation(async (id) => {
			const record = records.get(Number(id));
			return record ? { kind: 'live', record } : { kind: 'missing', reason: 'no-row' };
		});
		vi.spyOn(planetCatalogue, 'index').mockResolvedValue(null);
		const end = await resolveExtrasolarEnd(`x-${SYSTEM}`);
		expect(end?.body.id).toBe(`x-${PRIMARY}`);
		expect(end?.systemId).toBe(`x-${PRIMARY}`);
		expect(await resolveExtrasolarEnd('x-9')).toBeNull();
	});

	it('keeps a point that holds two stars, which is its own primary', async () => {
		const point = { ...starRecord(), id: 5 };
		point.rows = new Map([...point.rows, ['system', systemRow(5)]]);
		vi.spyOn(extrasolarLookup, 'live').mockResolvedValue({ kind: 'live', record: point });
		vi.spyOn(planetCatalogue, 'index').mockResolvedValue(null);
		expect((await resolveExtrasolarEnd('x-5'))?.body.id).toBe('x-5');
	});

	it('has no end for an object the export does not have', async () => {
		vi.spyOn(extrasolarLookup, 'live').mockResolvedValue({ kind: 'missing', reason: 'no-row' });
		vi.spyOn(planetCatalogue, 'planet').mockResolvedValue(null);
		expect(await resolveExtrasolarEnd('x-21238067')).toBeNull();
		expect(await resolveExtrasolarEnd('x-21238067-b-9')).toBeNull();
	});
});

describe.skipIf(!HAS_EXPORT)('a real giant at a point of several stars', () => {
	const lookup = new ExtrasolarLookup(diskSource());
	const BETELGEUSE = 22821649;
	const VY_CMA = 26993020;

	async function end(id: number) {
		vi.spyOn(extrasolarLookup, 'live').mockImplementation((x) => lookup.live(x));
		vi.spyOn(planetCatalogue, 'index').mockResolvedValue(null);
		return (await resolveExtrasolarEnd(`x-${id}`))!;
	}

	it('stops clear of Betelgeuse', async () => {
		const star = await end(BETELGEUSE);
		expect(star.star.radiusKm! / SOLAR_RADIUS_KM).toBeCloseTo(725.5, 1);
		const target = systemEndOf(extrasolarTravelBody(star)!, star, []);
		const home = systemEndOf(
			{
				id: 'naif-399',
				mu: GM_EARTH,
				muEstimated: false,
				radiusKm: 6378,
				elements: { a: 1, e: 0, i: 0, om: 0, w: 0, ma: 0, n: 0.9856, epoch: 2451545 }
			},
			null,
			[]
		);
		const options = { departureMode: 'orbit', arrivalMode: 'rendezvous' } as const;
		const route = buildInterstellarTorchRoute(home, target, 2460000, 9.8, options)!;
		const { targetStandOffKm } = heldLine(home, target, { ...options, ...route });
		expect(norm(targetStandOffKm) / star.star.radiusKm!).toBeCloseTo(2, 9);
	});

	it('gives VY CMa the radius of its paper', async () => {
		expect((await end(VY_CMA)).star.radiusKm! / SOLAR_RADIUS_KM).toBeCloseTo(1420, 3);
	});
});
