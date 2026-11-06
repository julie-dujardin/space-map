import { describe, expect, it } from 'vitest';
import { sizeText, type CompareObject } from './geometry';

/** The size the list, the labels and the fit give an object. */

const object = (geometry: CompareObject['geometry'], radiusKm = 6525): CompareObject => ({
	id: 'x-27424668-b-1',
	name: 'Proxima Cen b',
	radiusKm,
	geometry
});

describe('sizeText', () => {
	it('marks an estimated size', () => {
		expect(sizeText(object({ sizeEstimated: true }))).toBe('≈ 13,050 km');
	});

	it('gives a measured size as it stands', () => {
		expect(sizeText(object({}))).toBe('13,050 km');
	});

	it('gives a craft across its whole mesh', () => {
		expect(sizeText(object({ meshSpanRatio: 2 }, 0.01))).toBe('40 m');
	});
});
