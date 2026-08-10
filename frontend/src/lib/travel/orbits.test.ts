import { describe, expect, it } from 'vitest';
import { EARTH, JUPITER, MARS, MOON, VENUS } from '$lib/math/travel/test-fixtures';
import type { TravelBody } from '$lib/math/travel';
import type { BodyData } from '$lib/types/objects';
import { ObjectType } from '$lib/types/objects';
import {
	hasGround,
	hillPrimaryOf,
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
