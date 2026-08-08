import { describe, it, expect } from 'vitest';
import type { BodyData } from '$lib/types/objects';
import { ObjectType } from '$lib/types/objects';
import { heliocentricAncestor, lookupIn, naifId, toTravelBody, transferPlan } from './travel-body';

/** Minimal body row; only the fields the adapter reads are meaningful. */
function body(id: string, parentId: string, over: Partial<BodyData> = {}): BodyData {
	return {
		id,
		name: id,
		hasLocalized: false,
		objectType: ObjectType.PLANET,
		parentId,
		radiusKm: 1000,
		a: 1,
		e: 0.01,
		i: 0,
		om: 0,
		w: 0,
		ma: 0,
		n: 0.9856,
		epoch: 2451545,
		...over
	} as BodyData;
}

/** Sun, the two barycentres, and the bodies around them. */
function solarSystem() {
	const rows = [
		body('naif-10', 'naif-0'),
		body('naif-3', 'naif-10', { a: 1.00000261, n: 0.9856076 }),
		body('naif-399', 'naif-3', { a: 3.0e-5, radiusKm: 6371 }),
		body('naif-301', 'naif-3', { a: 2.57e-3, n: 13.1764, radiusKm: 1737.4 }),
		body('naif-5', 'naif-10', { a: 5.202887, n: 0.0830912 }),
		// Jupiter's own row is all zeroes in the export: its position comes from
		// sampled ephemeris, and it sits inside the barycentre either way.
		body('naif-599', 'naif-5', { a: 0, n: 0, radiusKm: 69911 }),
		body('naif-502', 'naif-5', { a: 4.4858e-3, n: 101.3747, radiusKm: 1560.8 }),
		body('naif-503', 'naif-5', { a: 7.1551e-3, n: 50.3176, radiusKm: 2631.2 })
	];
	return new Map(rows.map((r) => [r.id, r]));
}

describe('naifId', () => {
	it('reads the numeric part of a naif id', () => {
		expect(naifId('naif-499')).toBe(499);
		expect(naifId('naif-0')).toBe(0);
	});

	it('returns null for other id prefixes', () => {
		expect(naifId('spkid-2000004')).toBeNull();
		expect(naifId('probe-7')).toBeNull();
	});
});

describe('heliocentricAncestor', () => {
	const bodies = solarSystem();
	const look = lookupIn(bodies);

	it('resolves Earth to the Earth-Moon barycentre', () => {
		expect(heliocentricAncestor(bodies.get('naif-399')!, look)!.id).toBe('naif-3');
	});

	it('resolves a moon of another planet to that planet barycentre', () => {
		expect(heliocentricAncestor(bodies.get('naif-502')!, look)!.id).toBe('naif-5');
	});

	it('resolves a body already orbiting the Sun to itself', () => {
		const asteroid = body('spkid-2000004', 'naif-10');
		expect(heliocentricAncestor(asteroid, lookupIn(new Map()))!.id).toBe('spkid-2000004');
	});

	it('returns null when the chain cannot be walked', () => {
		const orphan = body('naif-9999', 'naif-8888');
		expect(heliocentricAncestor(orphan, lookupIn(new Map()))).toBeNull();
	});

	it('gives up rather than looping on a cycle', () => {
		const cyclic = new Map([
			['a', body('a', 'b')],
			['b', body('b', 'a')]
		]);
		expect(heliocentricAncestor(cyclic.get('a')!, lookupIn(cyclic))).toBeNull();
	});
});

describe('toTravelBody', () => {
	const bodies = solarSystem();
	const look = lookupIn(bodies);

	it('takes elements from the ancestor and size from the body', () => {
		const earth = toTravelBody(bodies.get('naif-399')!, look)!;
		expect(earth.radiusKm).toBe(6371);
		// The Earth-Moon barycentre's heliocentric orbit, not Earth's about it.
		expect(earth.elements.a).toBeCloseTo(1.00000261, 9);
	});

	it('estimates mu when no measured value is loaded', () => {
		// systems-global is unloaded in tests, so every body takes the fallback.
		const earth = toTravelBody(bodies.get('naif-399')!, look)!;
		expect(earth.muEstimated).toBe(true);
		expect(earth.mu).toBeGreaterThan(0);
	});

	function withPressure(level: string, pa = 101325) {
		return toTravelBody(bodies.get('naif-399')!, look, {
			atmosphere: { type: 'x', pressure: { pa, level } }
		} as never)!;
	}

	it('reads surface pressure into bar', () => {
		expect(withPressure('surface').surfacePressureBar).toBeCloseTo(1.01325, 5);
	});

	// The exporter quotes the ground under whichever name that body's geodesy
	// gives it; all three are the surface. Earth's says "sea_level", and reading
	// only "surface" priced it airless — no drag on ascent, no aerocapture.
	it('accepts every name the exporter gives the surface datum', () => {
		expect(withPressure('sea_level').surfacePressureBar).toBeCloseTo(1.01325, 5);
		expect(withPressure('areoid').surfacePressureBar).toBeCloseTo(1.01325, 5);
	});

	it('ignores a level with no surface under it', () => {
		expect(withPressure('cloud_top').surfacePressureBar).toBeUndefined();
		expect(withPressure('one_bar').surfacePressureBar).toBeUndefined();
	});

	it('treats a body with no detail as airless', () => {
		expect(toTravelBody(bodies.get('naif-399')!, look)!.surfacePressureBar).toBeUndefined();
	});

	it('returns null for a body with no reachable heliocentric orbit', () => {
		expect(toTravelBody(body('naif-9999', 'naif-8888'), lookupIn(new Map()))).toBeNull();
	});

	it('substitutes a positive radius for a missing one', () => {
		const sized = toTravelBody(
			body('naif-1234', 'naif-10', { radiusKm: NaN }),
			lookupIn(new Map())
		)!;
		expect(sized.radiusKm).toBeGreaterThan(0);
		expect(Number.isFinite(sized.mu)).toBe(true);
	});
});

describe('transferPlan', () => {
	const bodies = solarSystem();
	const look = lookupIn(bodies);
	const plan = (from: string, to: string) => transferPlan(bodies.get(from)!, bodies.get(to)!, look);

	it('sends bodies of different primaries round the Sun', () => {
		expect(plan('naif-399', 'naif-502')).toEqual({ kind: 'heliocentric' });
	});

	// Earth and its Moon share one heliocentric orbit, so there is no arc between
	// them out there; the transfer belongs about Earth, which is one of the ends.
	it('solves Earth to its own Moon about Earth', () => {
		expect(plan('naif-399', 'naif-301')).toEqual({ kind: 'system', primary: 'origin' });
	});

	it('solves the way back about Earth too', () => {
		expect(plan('naif-301', 'naif-399')).toEqual({ kind: 'system', primary: 'target' });
	});

	it('reads a planet as the centre of its own barycentre', () => {
		expect(plan('naif-502', 'naif-599')).toEqual({ kind: 'system', primary: 'target' });
	});

	// Neither end is the body the arc goes round, so it is an ordinary two-orbit
	// transfer again — about Jupiter rather than about the Sun.
	it('sends one moon to another of the same planet round their planet', () => {
		expect(plan('naif-502', 'naif-503')).toMatchObject({
			kind: 'sibling',
			centreId: 'naif-599'
		});
	});

	// systems-global is unloaded in tests, so the mass comes from Kepler's third
	// law on Europa's own orbit — which is exactly the fallback's job.
	it('recovers the planet mass from a moon it never looked up', () => {
		const solved = plan('naif-502', 'naif-503');
		const mu = solved.kind === 'sibling' ? solved.centralMu : NaN;
		// Jupiter's GM, 1.26687e8 km³/s², to within a tenth of a percent.
		expect(mu / 1.26687e8).toBeCloseTo(1, 3);
	});

	it('blocks a pair whose shared centre has no mass to be found', () => {
		const rows = [
			body('rock', 'naif-10'),
			body('rock-a', 'rock', { n: 0 }),
			body('rock-b', 'rock', { n: 0 })
		];
		const rocks = new Map(rows.map((r) => [r.id, r]));
		expect(transferPlan(rocks.get('rock-a')!, rocks.get('rock-b')!, lookupIn(rocks))).toEqual({
			kind: 'blocked',
			reason: 'unknown-primary'
		});
	});

	it('blocks a body whose orbit cannot be resolved', () => {
		expect(transferPlan(bodies.get('naif-399')!, body('naif-9999', 'naif-8888'), look)).toEqual({
			kind: 'blocked',
			reason: 'unknown-orbit'
		});
	});
});
