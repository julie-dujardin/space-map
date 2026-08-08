import { describe, it, expect } from 'vitest';
import type { BodyData } from '$lib/types/objects';
import { ObjectType } from '$lib/types/objects';
import { heliocentricAncestor, naifId, sameSystemBlock, toTravelBody } from './travel-body';

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

/** Sun, Earth-Moon barycentre, Earth, Moon, Jupiter barycentre, Europa. */
function solarSystem() {
	const rows = [
		body('naif-10', 'naif-0'),
		body('naif-3', 'naif-10', { a: 1.00000261, n: 0.9856076 }),
		body('naif-399', 'naif-3', { a: 3.0e-5, radiusKm: 6371 }),
		body('naif-301', 'naif-3', { a: 2.57e-3, radiusKm: 1737.4 }),
		body('naif-5', 'naif-10', { a: 5.202887, n: 0.0830912 }),
		body('naif-502', 'naif-5', { a: 4.485e-3, radiusKm: 1560.8 })
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

	it('resolves Earth to the Earth-Moon barycentre', () => {
		expect(heliocentricAncestor(bodies.get('naif-399')!, bodies)!.id).toBe('naif-3');
	});

	it('resolves a moon of another planet to that planet barycentre', () => {
		expect(heliocentricAncestor(bodies.get('naif-502')!, bodies)!.id).toBe('naif-5');
	});

	it('resolves a body already orbiting the Sun to itself', () => {
		const asteroid = body('spkid-2000004', 'naif-10');
		expect(heliocentricAncestor(asteroid, new Map())!.id).toBe('spkid-2000004');
	});

	it('returns null when the chain cannot be walked', () => {
		const orphan = body('naif-9999', 'naif-8888');
		expect(heliocentricAncestor(orphan, new Map())).toBeNull();
	});

	it('gives up rather than looping on a cycle', () => {
		const cyclic = new Map([
			['a', body('a', 'b')],
			['b', body('b', 'a')]
		]);
		expect(heliocentricAncestor(cyclic.get('a')!, cyclic)).toBeNull();
	});
});

describe('toTravelBody', () => {
	const bodies = solarSystem();

	it('takes elements from the ancestor and size from the body', () => {
		const earth = toTravelBody(bodies.get('naif-399')!, bodies)!;
		expect(earth.radiusKm).toBe(6371);
		// The Earth-Moon barycentre's heliocentric orbit, not Earth's about it.
		expect(earth.elements.a).toBeCloseTo(1.00000261, 9);
	});

	it('estimates mu when no measured value is loaded', () => {
		// systems-global is unloaded in tests, so every body takes the fallback.
		const earth = toTravelBody(bodies.get('naif-399')!, bodies)!;
		expect(earth.muEstimated).toBe(true);
		expect(earth.mu).toBeGreaterThan(0);
	});

	function withPressure(level: string, pa = 101325) {
		return toTravelBody(bodies.get('naif-399')!, bodies, {
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
		expect(toTravelBody(bodies.get('naif-399')!, bodies)!.surfacePressureBar).toBeUndefined();
	});

	it('returns null for a body with no reachable heliocentric orbit', () => {
		expect(toTravelBody(body('naif-9999', 'naif-8888'), new Map())).toBeNull();
	});

	it('substitutes a positive radius for a missing one', () => {
		const sized = toTravelBody(body('naif-1234', 'naif-10', { radiusKm: NaN }), new Map())!;
		expect(sized.radiusKm).toBeGreaterThan(0);
		expect(Number.isFinite(sized.mu)).toBe(true);
	});
});

describe('sameSystemBlock', () => {
	const bodies = solarSystem();

	it('allows a transfer between bodies of different primaries', () => {
		expect(sameSystemBlock(bodies.get('naif-399')!, bodies.get('naif-502')!, bodies)).toBeNull();
	});

	it('blocks Earth to its own Moon, which shares a primary', () => {
		expect(sameSystemBlock(bodies.get('naif-399')!, bodies.get('naif-301')!, bodies)).toBe(
			'same-primary'
		);
	});

	it('blocks a body whose orbit cannot be resolved', () => {
		expect(sameSystemBlock(bodies.get('naif-399')!, body('naif-9999', 'naif-8888'), bodies)).toBe(
			'unknown-orbit'
		);
	});
});
