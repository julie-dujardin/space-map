import { describe, expect, it } from 'vitest';
import { EARTH, JUPITER, MARS, MOON, VENUS } from '$lib/math/travel/test-fixtures';
import type { TravelBody } from '$lib/math/travel';
import type { BodyData } from '$lib/types/objects';
import { ObjectType } from '$lib/types/objects';
import {
	hasGround,
	hillPrimaryOf,
	isCraft,
	lowOrbitAltitudeKm,
	orbitChoices,
	synchronousRadiusKm,
	type OrbitFacts
} from './orbits';

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

describe('synchronousRadiusKm', () => {
	it('puts geostationary where it is', () => {
		expect(synchronousRadiusKm(EARTH.mu, EARTH_DAY_H)).toBeCloseTo(42164, -1);
	});

	it('puts areostationary where it is', () => {
		expect(synchronousRadiusKm(MARS.mu, MARS_SOL_H)).toBeCloseTo(20428, -1);
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
