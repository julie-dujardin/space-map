import { describe, expect, it } from 'vitest';
import { ObjectType, type BodyData } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { J2000_JD } from '$lib/time/jd';
import type { SGP4Inputs } from './sgp4';
import { elementsOffset, existsAt } from './offset';

function row(data: Partial<BodyData> = {}): BodyData {
	return {
		id: 'spkid-20000433',
		name: null,
		objectType: ObjectType.ASTEROID_INNER,
		parentId: 'naif-10',
		radiusKm: NaN,
		hasLocalized: false,
		a: 1.458,
		e: 0.223,
		i: 10.8,
		om: 304.3,
		w: 178.9,
		ma: 62.5,
		n: 0.5597,
		epoch: 2461200.5,
		validityStart: -Infinity,
		validityEnd: Infinity,
		orbitalSource: OrbitalSource.SBDB,
		...data
	};
}

describe('elementsOffset', () => {
	it('gives a finite offset for a Kepler row', () => {
		const offset = elementsOffset(row(), 2461300);
		expect(Array.isArray(offset)).toBe(true);
		expect((offset as number[]).every(Number.isFinite)).toBe(true);
		// Eros stays between its perihelion and aphelion, in scene units (10 per AU).
		const r = Math.hypot(...(offset as number[]));
		expect(r).toBeGreaterThan(11);
		expect(r).toBeLessThan(18);
	});

	it('has no place for a page-only row', () => {
		expect(elementsOffset(row({ pageOnly: true, a: NaN }), 2461300)).toBe('never');
	});

	it('has no place before the launch or discovery date', () => {
		const discovered = row({ visibleFromDays: 100 });
		expect(elementsOffset(discovered, J2000_JD + 99)).toBe('not-yet');
		expect(Array.isArray(elementsOffset(discovered, J2000_JD + 101))).toBe(true);
	});

	it('has no place outside the validity window of its file', () => {
		const sat = row({ validityStart: 2461000, validityEnd: 2461030 });
		expect(elementsOffset(sat, 2460999)).toBe('no-data');
		expect(elementsOffset(sat, 2461031)).toBe('no-data');
	});

	it('puts a planet with no offset of its own on its barycentre', () => {
		const mars = row({ objectType: ObjectType.PLANET, a: 0 });
		expect(elementsOffset(mars, 2461300)).toEqual([0, 0, 0]);
	});

	it('gives no place to a small body with no semi-major axis', () => {
		expect(elementsOffset(row({ a: 0 }), 2461300)).toBe('failed');
	});

	it('does not fall back to Kepler for an SGP4 row with no record', () => {
		const omm = {} as SGP4Inputs;
		expect(elementsOffset(row({ omm, satrec: undefined }), 2461300)).toBe('failed');
	});

	it('gives no place when the elements are not numbers', () => {
		expect(elementsOffset(row({ a: NaN, n: NaN }), 2461300)).toBe('failed');
	});
});

describe('existsAt', () => {
	it('holds at every date for a row with no gate', () => {
		expect(existsAt(row(), 0)).toBe(true);
		expect(existsAt(row({ visibleFromDays: NaN }), 0)).toBe(true);
	});
});
