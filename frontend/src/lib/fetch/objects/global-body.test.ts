/**
 * The bundle's answer to "is this object anywhere": the pipeline's
 * `Object.has_position`, read off the fields the client already holds.
 */

import { describe, expect, it } from 'vitest';
import { canBePlaced } from './global-body';
import type { GlobalObjectData } from './object-data';

function bundle(orbit?: Record<string, number>): GlobalObjectData {
	return { orbit } as unknown as GlobalObjectData;
}

const KEPLER = { epoch_jd: 2460000, a: 2.3, e: 0.1, i: 5, om: 20, w: 30, ma: 40, n: 0.2 };

describe('canBePlaced', () => {
	it('places an object with a full element set', () => {
		expect(canBePlaced('spkid-2000001', bundle(KEPLER))).toBe(true);
	});

	it('places a parabolic comet, which has no semi-major axis to give', () => {
		expect(canBePlaced('spkid-1000598', bundle({ epoch_jd: 2460000, q: 1.2, tp: 2460100 }))).toBe(
			true
		);
	});

	it('refuses a satellite the archive holds no elements for', () => {
		expect(canBePlaced('norad_satcat-2', bundle())).toBe(false);
	});

	it('refuses a moon published with half an orbit', () => {
		const partial = { ...KEPLER, n: undefined } as unknown as Record<string, number>;
		expect(canBePlaced('spkid-120000045', bundle(partial))).toBe(false);
	});

	it('places the bodies and probes that ride sampled ephemerides', () => {
		// Their bundles carry a placeholder orbit or none at all; the scene reads
		// their positions from the Chebyshev and probe chunks either way.
		expect(canBePlaced('naif-599', bundle({ ...KEPLER, a: 0 }))).toBe(true);
		expect(canBePlaced('probe-84353024', bundle())).toBe(true);
	});

	it('refuses an object with no bundle at all', () => {
		expect(canBePlaced('spkid-2000001', null)).toBe(false);
	});
});
