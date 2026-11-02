import { describe, expect, it } from 'vitest';
import { AU_KM } from '$lib/math/units';
import type { BodyData } from '$lib/types/objects';
import { ObjectType } from '$lib/types/objects';
import { starRingKm, tripBall } from './trip-ball';
import { DEFAULT_TRIP, type TripEnd, type TripState } from './trip';

function body(id: string, radiusKm: number, a = 0, e = 0): BodyData {
	return {
		id,
		name: id,
		objectType: ObjectType.EXTRASOLAR,
		parentId: '',
		radiusKm,
		a,
		e
	} as BodyData;
}

const STAR = body('x-558442032', 80_000);
const INNER = body('x-558442032-b-1', 6_000, 0.01);
const OUTER = body('x-558442032-b-4', 6_000, 0.03, 0.1);
const EARTH = body('naif-399', 6_378, 1);
const SUN = body('naif-10', 695_700);

function terms(ends: { origin?: Partial<TripEnd>; target?: Partial<TripEnd> } = {}): TripState {
	return {
		...DEFAULT_TRIP,
		ends: {
			origin: { ...DEFAULT_TRIP.ends.origin, ...ends.origin },
			target: { ...DEFAULT_TRIP.ends.target, ...ends.target }
		}
	};
}

describe('tripBall', () => {
	it('holds two planets of a star, out to the far end of the wider orbit', () => {
		const ball = tripBall(INNER, OUTER, terms())!;
		expect(ball.centerId).toBe('x-558442032');
		expect(ball.radiusKm).toBeCloseTo(0.033 * AU_KM, 3);
	});

	it('holds a planet and its star, either way round', () => {
		expect(tripBall(STAR, OUTER, terms())).toEqual(tripBall(OUTER, STAR, terms()));
		expect(tripBall(STAR, OUTER, terms())!.centerId).toBe('x-558442032');
	});

	it('takes a ring at the star that is wider than the orbit of the planet', () => {
		const wide = terms({ origin: { mode: 'custom', altKm: AU_KM, apoAltKm: 0 } });
		expect(tripBall(STAR, OUTER, wide)!.radiusKm).toBeCloseTo(AU_KM + 80_000, 3);
	});

	it('holds a change of orbit at a star round the star, out to the ring', () => {
		const ring = terms({ target: { mode: 'custom', altKm: 100 * AU_KM, apoAltKm: 100 * AU_KM } });
		expect(tripBall(STAR, STAR, ring)).toEqual({
			centerId: 'x-558442032',
			radiusKm: 100 * AU_KM + 80_000
		});
	});

	it('holds a change of orbit at a planet round the planet', () => {
		const ball = tripBall(OUTER, OUTER, terms())!;
		expect(ball.centerId).toBe('x-558442032-b-4');
		expect(ball.radiusKm).toBe(20 * 6_000);
	});

	it('leaves the solar system and a crossing to the opening they have', () => {
		const ring = terms({ target: { mode: 'custom', altKm: 100 * AU_KM, apoAltKm: 100 * AU_KM } });
		expect(tripBall(EARTH, SUN, ring)).toBeNull();
		expect(tripBall(SUN, SUN, ring)).toBeNull();
		expect(tripBall(EARTH, STAR, ring)).toBeNull();
	});

	it('has no ball for a trip with no size', () => {
		expect(tripBall(body('x-27424668', NaN), body('x-27424668', NaN), terms())).toBeNull();
		expect(tripBall(body('x-27424668-b-1', NaN), body('x-27424668-b-2', NaN), terms())).toBeNull();
	});
});

describe('starRingKm', () => {
	it('reads the wider custom orbit at a star end', () => {
		const ring = terms({
			origin: { mode: 'custom', altKm: 2 * AU_KM, apoAltKm: 3 * AU_KM },
			target: { mode: 'custom', altKm: AU_KM, apoAltKm: AU_KM }
		});
		expect(starRingKm(SUN, STAR, ring)).toBeCloseTo(3 * AU_KM + 695_700, 3);
	});

	it('leaves out an orbit at a planet, and every other mode', () => {
		const ring = terms({ origin: { mode: 'custom', altKm: AU_KM, apoAltKm: AU_KM } });
		expect(starRingKm(EARTH, STAR, ring)).toBe(0);
		expect(starRingKm(STAR, EARTH, terms())).toBe(0);
	});
});
