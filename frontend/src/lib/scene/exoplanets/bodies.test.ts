import { describe, expect, it } from 'vitest';
import type { PlanetSystem } from '$lib/fetch/extrasolar/planets';
import { orbitalElementsToPositionJD } from '$lib/math/orbit/position';
import { elementsOffset } from '$lib/math/orbit/offset';
import { AU_SCALE } from '$lib/math/units';
import { J2000_JD } from '$lib/time/jd';
import { ObjectType } from '$lib/types/objects';
import { NO_ORBIT_AU, NO_ORBIT_FACTOR, makePlanetBodies, outerOrbitAU } from './bodies';
import { ALPHA_CEN, elements, host, planet } from './__fixtures__/system';

/** The planets of a system file become bodies that orbit their own host. */

describe('planet bodies', () => {
	const bodies = makePlanetBodies(ALPHA_CEN);
	const byId = new Map(bodies.map((b) => [b.data.id, b]));

	it('makes one body per planet, orbiting its own host', () => {
		expect(bodies.map((b) => b.data.id)).toEqual([
			'x-27424668-b-1',
			'x-27424668-b-2',
			'x-564339647-b-1'
		]);
		expect(byId.get('x-27424668-b-1')!.data.parentId).toBe('x-27424668');
		expect(byId.get('x-564339647-b-1')!.data.parentId).toBe('x-564339647');
		for (const b of bodies) {
			expect(b.data.objectType).toBe(ObjectType.EXOPLANET);
			expect(b.position).toBeNull();
			expect(b.exoplanet?.system).toBe(27424668);
		}
		expect(byId.get('x-564339647-b-1')!.exoplanet!.hostRecord.id).toBe(564339647);
	});

	it('takes the elements as exported, with no time-scale switch', () => {
		const b = byId.get('x-27424668-b-1')!;
		expect(b.data).toMatchObject({ a: 0.0485, e: 0.1, i: 30, om: 40, w: 50, ma: 60, n: 1 });
		expect(b.data.epoch).toBe(2457000);
		expect(b.data.equatorial).toBeUndefined();
		expect(b.orbitElements).toBe(b.data);
		expect(b.orbitCenterId).toBe('x-27424668');
		// The offset is the Kepler place at every date: elements have no validity window.
		for (const jd of [2400000, 2460000, 2500000]) {
			expect(elementsOffset(b.data, jd)).toEqual(orbitalElementsToPositionJD(b.data, jd));
		}
	});

	it('keeps an assumed phase moving on its orbit', () => {
		const b = byId.get('x-27424668-b-2')!;
		expect(b.data.n).toBe(1);
		expect(b.exoplanet!.planet.elements!.phase).toBe('assumed');
	});

	it('sizes a planet from its radius in Jupiter radii, else leaves it unknown', () => {
		expect(byId.get('x-27424668-b-1')!.data.radiusKm).toBeCloseTo(0.0913 * 71492, 6);
		expect(byId.get('x-27424668-b-2')!.data.radiusKm).toBeNaN();
	});

	it('puts a planet with no orbit still, past its host outer orbit, with no orbit line', () => {
		const lone = byId.get('x-564339647-b-1')!;
		expect(lone.orbitElements).toBeUndefined();
		expect(lone.orbitCenterId).toBeUndefined();
		expect(lone.data.n).toBe(0);
		// Toliman has no orbit of its own: the stand-in span.
		expect(lone.data.a).toBe(NO_ORBIT_FACTOR * NO_ORBIT_AU);
		const at = elementsOffset(lone.data, J2000_JD) as number[];
		expect(Math.hypot(at[0], at[1], at[2])).toBeCloseTo(
			NO_ORBIT_FACTOR * NO_ORBIT_AU * AU_SCALE,
			9
		);
		expect(elementsOffset(lone.data, J2000_JD + 1e4)).toEqual(at);
	});

	it('spreads the planets with no orbit of one host round it, in its outer plane', () => {
		const file: PlanetSystem = {
			...ALPHA_CEN,
			hosts: [host(5, [1, 2, 3])],
			planets: [
				planet(5, 1, elements(0.2, { i: 80, om: 10 })),
				planet(5, 2, null),
				planet(5, 3, null)
			]
		};
		const [, a, b] = makePlanetBodies(file);
		expect(outerOrbitAU(file.planets)).toBe(0.2);
		for (const body of [a, b]) {
			expect(body.data).toMatchObject({ a: 0.2 * NO_ORBIT_FACTOR, e: 0, i: 80, om: 10, n: 0 });
		}
		expect([a.data.ma, b.data.ma]).toEqual([0, 180]);
	});
});
