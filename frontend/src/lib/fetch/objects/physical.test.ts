/** A body's mean radius comes from `radii`, else the SBDB diameter. */

import { describe, expect, it } from 'vitest';
import type { GlobalObjectData } from './object-data';
import { meanRadiusKm } from './physical';

const body = (fields: Partial<GlobalObjectData>) =>
	({ id: 'spkid-120050000', type: 'moon', ...fields }) as GlobalObjectData;

describe('meanRadiusKm', () => {
	it('averages the axes of the radii', () => {
		expect(meanRadiusKm(body({ radii: { a: 3, b: 2, c: 1 } }))).toBe(2);
	});

	it('halves the SBDB diameter when there are no radii', () => {
		expect(meanRadiusKm(body({ sbdb: { diameter: 192 } }))).toBe(96);
	});

	it('is null with neither', () => {
		expect(meanRadiusKm(body({}))).toBeNull();
	});
});
