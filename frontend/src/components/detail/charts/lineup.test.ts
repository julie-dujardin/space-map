/**
 * Tests `geometryFromMember`'s texture-flag plumbing: dropping the field
 * would silently revert every untextured member to a guaranteed-404 probe.
 * Plus the craft resolver, whose scale is the one thing keeping a probe
 * lineup honest.
 */

import { describe, expect, it } from 'vitest';
import { craftGeometryFromMember, geometryFromMember, renderableCount } from './lineup';

describe('geometryFromMember', () => {
	it('carries the texture flag through, including explicit false', () => {
		const base = { name: 'Pallas', id: 'spkid-20000002', diameter_km: 513 };
		expect(geometryFromMember({ ...base, texture: false })?.texture).toBe(false);
		expect(geometryFromMember({ ...base, texture: true })?.texture).toBe(true);
		// Pre-flag bundles omit the field — must stay undefined (probe as before).
		expect(geometryFromMember(base)?.texture).toBeUndefined();
	});
});

describe('craftGeometryFromMember', () => {
	const mro = { name: 'MRO', id: 'probe-1', model: 'mars-reconnaissance-orbiter', length_m: 13.6 };

	it('sizes a craft at half its span, in km', () => {
		// The convention the main scene uses, so one lineup can hold both kinds.
		expect(craftGeometryFromMember(mro)).toEqual({
			radiusKm: 0.0068,
			model: 'mars-reconnaissance-orbiter',
			craft: true
		});
	});

	it('drops a craft with no mesh or no measured span', () => {
		expect(craftGeometryFromMember({ ...mro, model: undefined })).toBeNull();
		expect(craftGeometryFromMember({ ...mro, length_m: undefined })).toBeNull();
	});

	it('ignores a body: a shape model alone is not a craft', () => {
		const eros = { name: 'Eros', id: 'spkid-1', model: 'eros', diameter_km: 16.8 };
		expect(craftGeometryFromMember(eros)).toBeNull();
		expect(renderableCount([eros, mro], craftGeometryFromMember)).toBe(1);
	});
});
