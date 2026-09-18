import { describe, expect, it } from 'vitest';
import { ObjectType, type BodyData } from '$lib/types/objects';
import { AU_KM } from '$lib/math/units';
import { subwayBodies } from './subway-bodies';

/** Minimal catalogue row; only what the adapter reads is meaningful. */
function row(id: string, parentId: string, over: Partial<BodyData> = {}): BodyData {
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

/** The Sun, two barycentres, and the bodies around them, as the export files them. */
function rows(): Map<string, BodyData> {
	const list = [
		row('naif-10', 'naif-0'),
		row('naif-3', 'naif-10', { a: 1.00000261 }),
		row('naif-399', 'naif-3', { a: 4670 / AU_KM, n: 13.18, radiusKm: 6371 }),
		row('naif-301', 'naif-3', { a: 384400 / AU_KM, n: 13.18, radiusKm: 1737 }),
		row('naif-4', 'naif-10', { a: 1.52371034, n: 0.524 }),
		row('naif-499', 'naif-4', { a: 0, n: 0, radiusKm: 3390 }),
		row('naif-2000001', 'naif-10', { a: 2.77, n: 0.214, radiusKm: 470 })
	];
	return new Map(list.map((b) => [b.id, b]));
}

describe('subwayBodies', () => {
	const bodies = subwayBodies(rows(), new Map());

	it('roots the tree at the Sun, a destination with no ground, and drops the barycentres', () => {
		expect(bodies.get('naif-10')?.primaryId).toBeNull();
		expect(bodies.get('naif-10')?.travel?.radiusKm).toBe(695700);
		expect(bodies.get('naif-10')?.ground).toBe(false);
		expect(bodies.has('naif-3')).toBe(false);
		expect(bodies.has('naif-4')).toBe(false);
	});

	it('hangs a planet off the Sun at its heliocentric distance', () => {
		const earth = bodies.get('naif-399')!;
		expect(earth.primaryId).toBe('naif-10');
		expect(earth.orbitRadiusKm / AU_KM).toBeCloseTo(1.00000261, 6);
		const mars = bodies.get('naif-499')!;
		expect(mars.primaryId).toBe('naif-10');
		expect(mars.orbitRadiusKm / AU_KM).toBeCloseTo(1.52371034, 6);
	});

	it('hangs a moon off its planet, not the barycentre they share', () => {
		const moon = bodies.get('naif-301')!;
		expect(moon.primaryId).toBe('naif-399');
		expect(moon.orbitRadiusKm).toBeCloseTo(384400, 0);
	});

	it('takes a body filed under the Sun as its own heliocentric orbit', () => {
		const ceres = bodies.get('naif-2000001')!;
		expect(ceres.primaryId).toBe('naif-10');
		expect(ceres.orbitRadiusKm / AU_KM).toBeCloseTo(2.77, 6);
	});

	it('gives an airless body ground to land on', () => {
		expect(bodies.get('naif-301')?.ground).toBe(true);
		expect(bodies.get('naif-499')?.ground).toBe(true);
	});
});
