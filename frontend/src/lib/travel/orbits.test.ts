import { describe, expect, it } from 'vitest';
import { EARTH, JUPITER, MARS, MOON, VENUS } from '$lib/math/travel/test-fixtures';
import {
	buildInterstellarCruiseRoute,
	buildInterstellarTorchRoute,
	GM_SUN_KM3_S2,
	type Route,
	type SystemEnd,
	type TravelBody
} from '$lib/math/travel';
import { LIGHT_YEAR_KM } from '$lib/math/units';
import { AU_KM } from '$lib/math/units';
import type { BodyData } from '$lib/types/objects';
import { ObjectType } from '$lib/types/objects';
import {
	altitudeScale,
	choicePriceKms,
	customReachKm,
	hasGround,
	isCraft,
	lowOrbitAltitudeKm,
	maxCustomAltitudeKm,
	maxRadiusKm,
	minCustomAltitudeKm,
	orbitChoices,
	orbitFacts,
	settledMode,
	synchronousRadiusKm,
	type OrbitFacts
} from './orbits';
import { hillPrimaryOf } from './travel-body';
import { DEFAULT_CUSTOM_ALT_KM } from './trip';

/** Sidereal days, hours. */
const EARTH_DAY_H = 23.9345;
const MARS_SOL_H = 24.6229;
/** The Moon's rotation is its month, which is what makes it a locked case. */
const LUNAR_MONTH_H = 655.72;
const VENUS_DAY_H = 5832.4;

const HILL: Record<string, number> = {
	earth: 1.496e6,
	mars: 1.084e6,
	venus: 1.004e6,
	moon: 61500,
	jupiter: 5.31e7
};

const OPTS = { hasSurface: true, customAltKm: 1000 };
const EARTH_FACTS: OrbitFacts = { rotationHours: EARTH_DAY_H, hillKm: HILL.earth };

function kinds(body: TravelBody, facts: OrbitFacts, role: 'origin' | 'target' = 'target') {
	return orbitChoices(body, facts, role, OPTS).map((c) => c.kind);
}

const STAR: TravelBody = {
	id: 'x-1',
	mu: 0.09 * GM_SUN_KM3_S2,
	muEstimated: true,
	radiusKm: 83_000,
	elements: { a: 0, e: 0, i: 0, om: 0, w: 0, ma: 0, n: 0, epoch: 0 }
};
const UNKNOWN_MASS: TravelBody = { ...STAR, mu: 0 };
const PLANET: TravelBody = { ...EARTH, id: 'x-1-b-1', parentId: 'x-1' };

const SUN_FACTS: OrbitFacts = { isStar: true, rotationHours: 609 };
const SUN: TravelBody = {
	id: 'naif-10',
	mu: GM_SUN_KM3_S2,
	muEstimated: false,
	radiusKm: 695_700,
	elements: STAR.elements
};
const FAR_STAR: OrbitFacts = { isStar: true, noPole: true };
const BETWEEN: OrbitFacts = { ...FAR_STAR, crossing: true };

describe('synchronousRadiusKm', () => {
	it('puts geostationary where it is', () => {
		expect(synchronousRadiusKm(EARTH.mu, EARTH_DAY_H)).toBeCloseTo(42164, -1);
	});

	it('puts areostationary where it is', () => {
		expect(synchronousRadiusKm(MARS.mu, MARS_SOL_H)).toBeCloseTo(20428, -1);
	});
});

describe('a star as an end', () => {
	it('offers a hold, a custom orbit and a flyby between two systems', () => {
		expect(kinds(STAR, BETWEEN)).toEqual(['rendezvous', 'custom', 'flyby']);
		expect(kinds(STAR, BETWEEN, 'origin')).toEqual(['rendezvous', 'custom']);
	});

	it('offers the Sun the same between two systems', () => {
		const facts = { ...SUN_FACTS, crossing: true };
		expect(kinds(SUN, facts)).toEqual(['rendezvous', 'custom', 'flyby']);
		expect(kinds(SUN, facts, 'origin')).toEqual(['rendezvous', 'custom']);
	});

	it('keeps a hold and a flyby at a star of unknown mass, on any trip', () => {
		expect(kinds(UNKNOWN_MASS, BETWEEN)).toEqual(['rendezvous', 'flyby']);
		expect(kinds(UNKNOWN_MASS, BETWEEN, 'origin')).toEqual(['rendezvous']);
		expect(kinds(UNKNOWN_MASS, FAR_STAR)).toEqual(['rendezvous', 'flyby']);
	});

	it('offers what the Sun offers inside its own system, and no ground', () => {
		expect(kinds(STAR, FAR_STAR)).toEqual(['elliptical', 'low-orbit', 'custom', 'flyby']);
		expect(kinds(STAR, FAR_STAR, 'origin')).toEqual(['low-orbit', 'custom']);
		const sun = kinds(SUN, SUN_FACTS);
		expect(sun).not.toContain('surface');
		expect(sun).not.toContain('rendezvous');
		expect(sun).toEqual(expect.arrayContaining(['low-orbit', 'custom', 'flyby']));
	});

	it('reaches 1000 au from any star, the Sun included', () => {
		const reach = 1000 * AU_KM;
		expect(maxRadiusKm(FAR_STAR)).toBe(reach);
		expect(maxRadiusKm(SUN_FACTS)).toBe(reach);
		expect(maxCustomAltitudeKm(STAR, FAR_STAR)).toBe(reach - STAR.radiusKm);
		expect(maxCustomAltitudeKm(SUN, SUN_FACTS)).toBe(reach - SUN.radiusKm);

		const wide = { hasSurface: false, customAltKm: 5000 * AU_KM, customApoAltKm: 9000 * AU_KM };
		for (const [body, facts] of [
			[STAR, BETWEEN],
			[SUN, SUN_FACTS]
		] as const) {
			const custom = orbitChoices(body, facts, 'target', wide).find((c) => c.kind === 'custom')!;
			expect(custom.orbit).toEqual({ rPeriKm: reach, rApoKm: reach });
		}
	});

	it('starts the control just over the surface of a star, and at 1 km elsewhere', () => {
		expect(minCustomAltitudeKm(STAR, FAR_STAR)).toBe(830);
		expect(minCustomAltitudeKm({ ...STAR, radiusKm: 1 }, FAR_STAR)).toBe(1);
		expect(minCustomAltitudeKm(EARTH, EARTH_FACTS)).toBe(1);
	});

	it('opens the custom row on a place the control can show, at any size of star', () => {
		// A forecast radius of 0.45 solar radii, and the Sun's.
		for (const radiusKm of [313_000, 695_700]) {
			const star = { ...STAR, radiusKm };
			expect(minCustomAltitudeKm(star, FAR_STAR)).toBe(DEFAULT_CUSTOM_ALT_KM);
			const row = orbitChoices(star, FAR_STAR, 'target', {
				hasSurface: false,
				customAltKm: DEFAULT_CUSTOM_ALT_KM
			}).find((c) => c.kind === 'custom')!;
			expect(row.periAltKm).toBeCloseTo(DEFAULT_CUSTOM_ALT_KM, 6);
			const scale = altitudeScale(minCustomAltitudeKm(star, FAR_STAR), 1000 * AU_KM);
			expect(scale.position(row.periAltKm!)).toBe(0);
			expect(scale.altitude(0)).toBe(DEFAULT_CUSTOM_ALT_KM);
		}
	});

	it('holds a period of tens of thousands of years', () => {
		const options = { hasSurface: false, customAltKm: 900 * AU_KM };
		const custom = orbitChoices(STAR, BETWEEN, 'target', options).find((c) => c.kind === 'custom')!;
		expect(custom.periodHours! / 24 / 365.25).toBeGreaterThan(90_000);
	});
});

describe('a body with no known pole', () => {
	const NAMED = {
		hasSurface: false,
		customAltKm: 1000,
		customApoAltKm: 5000,
		incDeg: 40,
		argPeriDeg: 90
	};
	const customAt = (body: TravelBody, facts: OrbitFacts) =>
		orbitChoices(body, facts, 'target', NAMED).find((c) => c.kind === 'custom')!.orbit!;

	it('leaves the plane of a custom orbit free, whatever a link says', () => {
		for (const [body, facts] of [
			[STAR, BETWEEN],
			[STAR, FAR_STAR],
			[PLANET, { noPole: true }]
		] as const) {
			const orbit = customAt(body, facts);
			expect(orbit.incDeg).toBeUndefined();
			expect(orbit.argPeriDeg).toBeUndefined();
		}
	});

	it('keeps the plane at the Sun, which has a pole', () => {
		const orbit = customAt(SUN, { ...SUN_FACTS, crossing: true });
		expect(orbit.incDeg).toBe(40);
		expect(orbit.argPeriDeg).toBe(90);
	});

	it('reads the facts off the body', () => {
		const row = (id: string) => ({ id, objectType: ObjectType.PLANET }) as BodyData;
		const star = { isStar: true, noPole: true };
		expect(orbitFacts(row('x-27424668'), STAR, null)).toMatchObject(star);
		expect(orbitFacts(row('x-27424668-b-1'), PLANET, null)).toMatchObject({
			...star,
			isStar: false
		});
		expect(orbitFacts(row('naif-10'), SUN, null)).toMatchObject({ ...star, noPole: false });
		expect(orbitFacts(row('naif-399'), EARTH, null)).toMatchObject({
			isStar: false,
			noPole: false
		});
	});
});

describe('the price of a choice at a star', () => {
	const J2000 = 2451545;
	const HOME: SystemEnd = { body: EARTH, starKm: [0, 0, 0], starMu: GM_SUN_KM3_S2, atStar: false };
	const FAR: SystemEnd = {
		body: STAR,
		starKm: [4 * LIGHT_YEAR_KM, 0, 0],
		starMu: STAR.mu,
		atStar: true
	};
	const WIDE = 2 * AU_KM;
	const options = { hasSurface: false, customAltKm: WIDE, customApoAltKm: 0 };
	const choices = orbitChoices(STAR, BETWEEN, 'target', options);
	const custom = choices.find((c) => c.kind === 'custom')!;
	const hold = choices.find((c) => c.kind === 'rendezvous')!;

	/** The cost of the arrival of `route`, by its legs. */
	const arrivalKms = (route: Route) =>
		route.legs
			.filter((leg) => leg.kind === 'capture' || leg.kind === 'rendezvous')
			.reduce((sum, leg) => sum + leg.dvKms, 0);

	/** A budget this size coasts at a good part of the speed of light. */
	function coast(terms: Parameters<typeof buildInterstellarCruiseRoute>[4]): Route {
		const drive = { kind: 'budget', dvKms: 150_000 } as const;
		return buildInterstellarCruiseRoute(HOME, FAR, J2000, drive, {
			departureMode: 'orbit',
			...terms
		}) as Route;
	}

	it('reads the price of the route for a custom orbit, at any speed', () => {
		const route = coast({ arrivalMode: 'low-orbit', targetOrbit: custom.orbit });
		expect(route.interstellar!.cruiseKms).toBeGreaterThan(30_000);
		const hint = choicePriceKms(route, STAR, 'target', custom, 'none', true)!;
		expect(hint / arrivalKms(route)).toBeCloseTo(1, 6);
	});

	it('reads the price of the hold at 1 au, not the speed of the coast', () => {
		const route = coast({ arrivalMode: 'rendezvous' });
		const hint = choicePriceKms(route, STAR, 'target', hold, 'none', true)!;
		expect(hint / arrivalKms(route)).toBeCloseTo(1, 6);
	});

	it('reads what leaving a custom orbit costs at a star', () => {
		const route = buildInterstellarCruiseRoute(
			FAR,
			HOME,
			J2000,
			{ kind: 'budget', dvKms: 300 },
			{ departureMode: 'orbit', arrivalMode: 'flyby', departureOrbit: custom.orbit }
		) as Route;
		const origin = orbitChoices(STAR, BETWEEN, 'origin', options).find((c) => c.kind === 'custom')!;
		const hint = choicePriceKms(route, STAR, 'origin', origin, 'none', true)!;
		const injection = route.legs.find((leg) => leg.kind === 'injection')!.dvKms;
		expect(hint / injection).toBeCloseTo(1, 6);
	});

	it('reads no burn from a held drive, which stops at rest', () => {
		const route = buildInterstellarTorchRoute(HOME, FAR, J2000, 9.8, {
			departureMode: 'orbit',
			arrivalMode: 'rendezvous'
		})!;
		expect(choicePriceKms(route, STAR, 'target', hold, 'none', true)).toBeCloseTo(0, 6);
	});

	it('reads the price of the hold at 2 radii of a giant', () => {
		const giant = { ...STAR, radiusKm: 8 * AU_KM };
		const route = buildInterstellarCruiseRoute(
			HOME,
			{ ...FAR, body: giant },
			J2000,
			{ kind: 'budget', dvKms: 150_000 },
			{ departureMode: 'orbit', arrivalMode: 'rendezvous' }
		) as Route;
		const hint = choicePriceKms(route, giant, 'target', hold, 'none', true)!;
		expect(hint / arrivalKms(route)).toBeCloseTo(1, 6);
	});

	it('reads no pass through the air from a held stop', () => {
		const route = buildInterstellarTorchRoute(FAR, HOME, J2000, 9.8, {
			departureMode: 'rendezvous',
			arrivalMode: 'low-orbit',
			aero: 'aerocapture'
		})!;
		const low = orbitChoices(EARTH, {}, 'target', OPTS).find((c) => c.kind === 'low-orbit')!;
		const engine = choicePriceKms(route, EARTH, 'target', low, 'none', false);
		expect(choicePriceKms(route, EARTH, 'target', low, 'aerocapture', false)).toBe(engine);
	});

	it('names no price for a flyby', () => {
		const flyby = choices.find((c) => c.kind === 'flyby')!;
		const route = coast({ arrivalMode: 'flyby' });
		expect(choicePriceKms(route, STAR, 'target', flyby, 'none', true)).toBeNull();
	});
});

describe('settledMode', () => {
	const list = (body: TravelBody, facts: OrbitFacts) => orbitChoices(body, facts, 'target', OPTS);

	it('keeps a mode the end can hold', () => {
		expect(settledMode(list(STAR, BETWEEN), 'custom')).toBe('custom');
	});

	it('falls back from a custom orbit at a star of unknown mass', () => {
		expect(settledMode(list(UNKNOWN_MASS, BETWEEN), 'custom')).toBe('rendezvous');
	});

	it('takes a hold off a star inside its own system', () => {
		expect(settledMode(list(STAR, FAR_STAR), 'rendezvous')).toBe('low-orbit');
	});

	it('takes the ground off a star', () => {
		expect(settledMode(list(STAR, BETWEEN), 'surface')).toBe('rendezvous');
		expect(settledMode(list(STAR, FAR_STAR), 'surface')).toBe('low-orbit');
	});
});

describe('orbitChoices', () => {
	it('offers the named orbits of a body that turns fast enough to have them', () => {
		expect(kinds(EARTH, { rotationHours: EARTH_DAY_H, hillKm: HILL.earth })).toEqual([
			'surface',
			'elliptical',
			'low-orbit',
			'semi-sync',
			'stationary',
			'transfer',
			'heo',
			'custom',
			'flyby'
		]);
	});

	it('measures the stationary orbit it offers', () => {
		const stationary = orbitChoices(
			EARTH,
			{ rotationHours: EARTH_DAY_H, hillKm: HILL.earth },
			'target',
			OPTS
		).find((c) => c.kind === 'stationary');
		expect(stationary?.periAltKm).toBeCloseTo(35793, -1);
		expect(stationary?.periodHours).toBeCloseTo(EARTH_DAY_H, 1);
	});

	// The one rule that does the most work: a day longer than the space the body
	// holds means the orbit that would keep pace with it is not bound at all.
	it('drops the stationary orbit at a body that turns too slowly', () => {
		expect(kinds(VENUS, { rotationHours: VENUS_DAY_H, hillKm: HILL.venus })).not.toContain(
			'stationary'
		);
	});

	// Synchronous works out at 3^(1/3) Hill radii for every tidally locked moon,
	// so this holds for Titan and Europa as much as for the Moon.
	it('drops it for a tidally locked moon, whose day is its month', () => {
		expect(kinds(MOON, { rotationHours: LUNAR_MONTH_H, hillKm: HILL.moon })).not.toContain(
			'stationary'
		);
	});

	it('offers nothing named when the spin is unknown', () => {
		expect(kinds(EARTH, { hillKm: HILL.earth })).toEqual([
			'surface',
			'elliptical',
			'low-orbit',
			'custom',
			'flyby'
		]);
	});

	it('leaves a departure the shapes it can actually set out from', () => {
		const departure = kinds(EARTH, { rotationHours: EARTH_DAY_H, hillKm: HILL.earth }, 'origin');
		expect(departure).not.toContain('flyby');
		expect(departure).not.toContain('elliptical');
		expect(departure).not.toContain('transfer');
		expect(departure).toContain('stationary');
	});

	it('has nothing to land on where there is no ground', () => {
		expect(
			orbitChoices(JUPITER, { rotationHours: 9.925, hillKm: HILL.jupiter }, 'target', {
				...OPTS,
				hasSurface: false
			}).map((c) => c.kind)
		).not.toContain('surface');
	});

	it('keeps a custom orbit inside what the body holds', () => {
		const custom = orbitChoices(MOON, { hillKm: HILL.moon }, 'target', {
			hasSurface: true,
			customAltKm: 1e9
		}).find((c) => c.kind === 'custom');
		expect(custom?.orbit?.rApoKm).toBeLessThanOrEqual(HILL.moon / 3);
	});

	// The custom orbit is the only one the trip shapes, so the far end goes to it
	// and to no other — a named orbit given one would be a second orbit under the
	// same name.
	it('gives the far end the trip named to the custom orbit and to no other', () => {
		const choices = orbitChoices(EARTH, EARTH_FACTS, 'target', {
			...OPTS,
			customAltKm: 600,
			customApoAltKm: 39750
		});
		const custom = choices.find((c) => c.kind === 'custom');
		expect(custom?.periAltKm).toBeCloseTo(600, 6);
		expect(custom?.apoAltKm).toBeCloseTo(39750, 6);
		// A Molniya's half-day period comes out of the shape alone.
		expect(custom?.periodHours).toBeCloseTo(11.97, 1);
		for (const choice of choices) {
			if (choice.kind === 'custom' || choice.orbit === undefined) continue;
			expect(choice.orbit.rApoKm, choice.kind).not.toBeCloseTo(EARTH.radiusKm + 39750, 6);
		}
	});

	// An orbit whose far end is under its near one is not an orbit, and the near
	// end is the one the trip set on purpose.
	it('never puts the far end of a custom orbit under the near one', () => {
		const custom = orbitChoices(EARTH, EARTH_FACTS, 'target', {
			...OPTS,
			customAltKm: 5000,
			customApoAltKm: 800
		}).find((c) => c.kind === 'custom');
		expect(custom?.periAltKm).toBeCloseTo(5000, 6);
		expect(custom?.apoAltKm).toBeCloseTo(5000, 6);
	});

	it('keeps the far end of a custom orbit inside what the body holds', () => {
		const custom = orbitChoices(MOON, { hillKm: HILL.moon }, 'target', {
			hasSurface: true,
			customAltKm: 200,
			customApoAltKm: 1e9
		}).find((c) => c.kind === 'custom');
		expect(custom?.orbit?.rApoKm).toBeLessThanOrEqual(HILL.moon / 3);
		expect(custom?.orbit?.rPeriKm).toBeCloseTo(MOON.radiusKm + 200, 6);
	});

	// A named orbit is named for its shape, so the plane goes to the one orbit
	// that is not: flying "stationary orbit" in two planes would be two entries
	// under one name.
	it('gives the plane the trip named to the custom orbit and to no other', () => {
		for (const choice of orbitChoices(EARTH, EARTH_FACTS, 'target', { ...OPTS, incDeg: 63.4 })) {
			if (!choice.orbit || choice.kind === 'stationary') continue;
			expect(choice.orbit.incDeg, choice.kind).toBe(choice.kind === 'custom' ? 63.4 : undefined);
		}
	});

	// An unnamed plane has to stay unnamed: naming it would price a turn into an
	// orbit nobody asked to be in.
	it('leaves the plane off when the trip names none', () => {
		for (const choice of orbitChoices(EARTH, EARTH_FACTS, 'target', OPTS)) {
			if (choice.kind === 'stationary') continue;
			expect(choice.orbit?.incDeg, choice.kind).toBeUndefined();
		}
	});

	// The one orbit whose plane is not the trip's to choose: off the equator it
	// drifts over the ground and is no longer the orbit that was asked for.
	it('holds the stationary orbit to the equator whatever the trip names', () => {
		for (const incDeg of [null, 63.4]) {
			const stationary = orbitChoices(EARTH, EARTH_FACTS, 'target', { ...OPTS, incDeg }).find(
				(c) => c.kind === 'stationary'
			);
			expect(stationary?.orbit?.incDeg).toBe(0);
		}
	});

	it('takes the equator as a plane like any other', () => {
		const custom = orbitChoices(EARTH, EARTH_FACTS, 'target', { ...OPTS, incDeg: 0 }).find(
			(c) => c.kind === 'custom'
		);
		expect(custom?.orbit?.incDeg).toBe(0);
	});
});

describe('orbitChoices at a craft', () => {
	// A spacecraft's own gravity holds nothing, so every named orbit round one is
	// a shape nothing could fly — it is met or passed and nothing else.
	const CRAFT_FACTS: OrbitFacts = { isCraft: true, hillKm: HILL.earth };
	const CRAFT: TravelBody = { ...EARTH, id: 'probe-voyager-1', mu: 1e-12, radiusKm: 0.01 };

	it('offers only a rendezvous and a pass at a destination craft', () => {
		expect(kinds(CRAFT, CRAFT_FACTS)).toEqual(['rendezvous', 'flyby']);
	});

	it('offers only a rendezvous to leave one from', () => {
		expect(kinds(CRAFT, CRAFT_FACTS, 'origin')).toEqual(['rendezvous']);
	});

	it('names no orbit for the rendezvous, since it is not one', () => {
		expect(orbitChoices(CRAFT, CRAFT_FACTS, 'target', OPTS)[0].orbit).toBeUndefined();
	});
});

describe('isCraft', () => {
	const typed = (objectType: ObjectType): BodyData => ({ objectType }) as BodyData;

	it('counts a spacecraft and the pieces of one', () => {
		expect(isCraft(typed(ObjectType.SPACECRAFT))).toBe(true);
		expect(isCraft(typed(ObjectType.DEBRIS))).toBe(true);
	});

	it('does not count a body', () => {
		expect(isCraft(typed(ObjectType.MOON))).toBe(false);
	});
});

describe('the custom orbit at a body with little room', () => {
	/** Phobos, with a third of its Hill radius under its surface. */
	const SMALL: TravelBody = { ...MOON, id: 'naif-401', radiusKm: 11, mu: 7.1e-4 };
	const ROOM: OrbitFacts = { hillKm: 16 };
	const NO_ROOM: OrbitFacts = { hillKm: 9 };
	const row = (body: TravelBody, facts: OrbitFacts, role: 'origin' | 'target' = 'target') =>
		orbitChoices(body, facts, role, {
			hasSurface: true,
			customAltKm: DEFAULT_CUSTOM_ALT_KM,
			customApoAltKm: DEFAULT_CUSTOM_ALT_KM
		}).find((c) => c.kind === 'custom');

	it('reaches a third of the Hill radius where that clears the low orbit', () => {
		expect(customReachKm(EARTH, EARTH_FACTS)).toBeCloseTo(HILL.earth / 3, 6);
		expect(customReachKm(STAR, FAR_STAR)).toBe(1000 * AU_KM);
		expect(customReachKm(EARTH, {})).toBe(Infinity);
	});

	it('reaches the whole Hill radius where a third falls under the surface', () => {
		expect(customReachKm(SMALL, ROOM)).toBe(16);
		expect(row(SMALL, ROOM)).toMatchObject({ orbit: { rPeriKm: 16, rApoKm: 16 } });
		expect(row(SMALL, ROOM, 'origin')?.apoAltKm).toBe(5);
	});

	it('reaches the low orbit itself where the whole Hill radius falls under the surface', () => {
		const rLow = SMALL.radiusKm + lowOrbitAltitudeKm(SMALL, NO_ROOM);
		expect(customReachKm(SMALL, NO_ROOM)).toBe(rLow);
		expect(row(SMALL, NO_ROOM)).toMatchObject({ orbit: { rPeriKm: rLow, rApoKm: rLow } });
	});

	it('leaves every named row where it was', () => {
		const named = (facts: OrbitFacts) =>
			orbitChoices(SMALL, facts, 'target', { hasSurface: true, customAltKm: 500 }).filter(
				(c) => c.kind !== 'custom'
			);
		expect(maxRadiusKm(ROOM)).toBeCloseTo(16 / 3, 9);
		expect(named(ROOM).map((c) => c.kind)).toEqual(['surface', 'low-orbit', 'flyby']);
		expect(named(ROOM).find((c) => c.kind === 'low-orbit')?.periAltKm).toBeCloseTo(0.001, 9);
	});

	it('keeps a body with room on the reach it had', () => {
		const wide = orbitChoices(EARTH, EARTH_FACTS, 'target', {
			hasSurface: true,
			customAltKm: 1e9
		}).find((c) => c.kind === 'custom')!;
		expect(wide.orbit?.rPeriKm).toBeCloseTo(HILL.earth / 3, 6);
		expect(maxCustomAltitudeKm(EARTH, EARTH_FACTS)).toBeCloseTo(HILL.earth / 3 - EARTH.radiusKm, 6);
	});

	it('gives the control a range that fits the room', () => {
		for (const facts of [ROOM, NO_ROOM, { hillKm: 12 }, { hillKm: 11.2 }]) {
			const min = minCustomAltitudeKm(SMALL, facts);
			const max = maxCustomAltitudeKm(SMALL, facts);
			expect(max).toBeGreaterThan(0);
			expect(min).toBeLessThanOrEqual(max);
		}
		expect(maxCustomAltitudeKm(SMALL, ROOM)).toBe(5);
		expect(minCustomAltitudeKm(SMALL, ROOM)).toBe(1);
		const empty = maxCustomAltitudeKm(SMALL, NO_ROOM);
		expect(minCustomAltitudeKm(SMALL, NO_ROOM)).toBe(empty);
	});

	it('still only meets or passes a craft', () => {
		const facts: OrbitFacts = { isCraft: true, hillKm: 0.001 };
		expect(row({ ...SMALL, radiusKm: 0.01 }, facts)).toBeUndefined();
		expect(kinds({ ...SMALL, radiusKm: 0.01 }, facts)).toEqual(['rendezvous', 'flyby']);
	});
});

describe('altitudeScale', () => {
	it('runs from one end of the range to the other', () => {
		const scale = altitudeScale(1, 1e5);
		expect(scale.steps).toBe(875);
		expect(scale.position(1)).toBe(0);
		expect(scale.position(1e5)).toBe(875);
		expect(scale.altitude(0)).toBe(1);
		expect(scale.altitude(875)).toBe(1e5);
	});

	it('comes back to the altitude it was given, to a step', () => {
		const scale = altitudeScale(1, 1.5e11);
		for (const km of [600, 39750, 1e9]) {
			const share = scale.altitude(scale.position(km)) / km;
			expect(Math.abs(Math.log10(share))).toBeLessThan(1 / 175);
		}
	});

	it('holds what it is given inside the range', () => {
		const scale = altitudeScale(10, 1000);
		expect(scale.position(1)).toBe(0);
		expect(scale.position(1e6)).toBe(scale.steps);
	});

	it('has no steps on an empty, an inverted or an unknown range', () => {
		for (const [min, max] of [
			[0.4, 0.4],
			[1, 0.4],
			[1, 0],
			[0.001, 0.001]
		]) {
			const scale = altitudeScale(min, max);
			expect(scale.steps).toBe(0);
			expect(scale.position(1000)).toBe(0);
			expect(scale.altitude(0)).toBe(min);
		}
	});

	it('sets tenths on a short range, so that it can move', () => {
		const scale = altitudeScale(1, 1.4);
		expect(scale.altitude(scale.steps)).toBe(1.4);
		expect(scale.altitude(0)).toBe(1);
		expect(altitudeScale(1, 3.3148).altitude(91)).toBe(3.3);
	});

	it('stays a number on a range too small for one step', () => {
		const scale = altitudeScale(1, 1.0001);
		expect(scale.steps).toBe(0);
		expect(scale.position(1.00005)).toBe(0);
		expect(altitudeScale(1, 1.2).steps).toBeGreaterThan(0);
		expect(Number.isFinite(altitudeScale(1, 1.2).position(1.1))).toBe(true);
	});
});

describe('lowOrbitAltitudeKm', () => {
	it("is the kernel's parking altitude wherever the body has the room", () => {
		expect(lowOrbitAltitudeKm(EARTH, { hillKm: HILL.earth })).toBe(200);
		expect(lowOrbitAltitudeKm(MOON, { hillKm: HILL.moon })).toBe(200);
	});

	// 200 km above a kilometre-wide asteroid is outside what it holds, so the
	// altitude comes off the ceiling instead — this is the body from the panel.
	it('comes off the ceiling at a body with no room for one', () => {
		const pebble: TravelBody = { ...MOON, radiusKm: 1, mu: 1e-7 };
		// A Hill radius of 483 km leaves 160 km of usable ceiling.
		expect(lowOrbitAltitudeKm(pebble, { hillKm: 483 })).toBeCloseTo(40, 0);
	});

	it('falls back to the parking altitude when the room is unknown', () => {
		expect(lowOrbitAltitudeKm(EARTH, {})).toBe(200);
	});
});

describe('hasGround', () => {
	it('is false for an envelope with no surface reading under it', () => {
		const giant: TravelBody = { ...JUPITER, hasAtmosphere: true, surfacePressureBar: undefined };
		expect(hasGround(giant)).toBe(false);
	});

	it('is true for a body that quotes a pressure at its own surface', () => {
		expect(hasGround({ ...EARTH, hasAtmosphere: true })).toBe(true);
	});

	// A body whose detail has not landed yet claims ground, which every rocky
	// body turns out to have — the giants are the exception, and they are known.
	it('is true while nothing is known about the air', () => {
		expect(hasGround(MOON)).toBe(true);
	});
});

describe('hillPrimaryOf', () => {
	const at = (id: string, parentId: string): BodyData =>
		({ id, parentId, objectType: ObjectType.MOON }) as BodyData;

	it('holds a planet against the Sun, not against its own barycentre', () => {
		expect(hillPrimaryOf(at('naif-399', 'naif-3'))).toBe('sun');
	});

	// The case that gave the Moon a stationary orbit: same barycentre as Earth,
	// but held by Earth rather than by the Sun.
	it('holds a moon of that barycentre against the planet inside it', () => {
		expect(hillPrimaryOf(at('naif-301', 'naif-3'))).toBe(399);
	});

	it('holds a moon of a planet against that planet', () => {
		expect(hillPrimaryOf(at('naif-502', 'naif-599'))).toBe(599);
	});

	it('holds anything orbiting the Sun against the Sun', () => {
		expect(hillPrimaryOf(at('spkid-2000001', 'naif-10'))).toBe('sun');
	});
});
