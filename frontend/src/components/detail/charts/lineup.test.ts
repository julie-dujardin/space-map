/**
 * Tests `geometryFromMember`'s texture-flag plumbing: dropping the field
 * would silently revert every untextured member to a guaranteed-404 probe.
 * Plus the craft resolver, whose scale is the one thing keeping a probe
 * lineup honest.
 */

import { describe, expect, it } from 'vitest';
import {
	craftGeometryFromMember,
	geometryFromMember,
	renderableCount,
	starGeometryFromMember
} from './lineup';

describe('geometryFromMember', () => {
	it('carries the texture flag through, including explicit false', () => {
		const base = { name: 'Pallas', id: 'spkid-20000002', diameter_km: 513 };
		expect(geometryFromMember({ ...base, texture: false })?.texture).toBe(false);
		expect(geometryFromMember({ ...base, texture: true })?.texture).toBe(true);
		// Pre-flag bundles omit the field — must stay undefined (probe as before).
		expect(geometryFromMember(base)?.texture).toBeUndefined();
	});

	it('leaves out a star of another system, which a row of stars draws', () => {
		expect(
			geometryFromMember({ name: 'TRAPPIST-1', id: 'x-558442032', diameter_km: 167000 })
		).toBeNull();
	});

	it('draws an exoplanet with its map, whatever its entry says', () => {
		const planet = { name: 'TRAPPIST-1 e', id: 'x-558442032-b-4', diameter_km: 11740 };
		const drawn = { radiusKm: 5870, texture: true };
		expect(geometryFromMember({ ...planet, texture: true })).toMatchObject(drawn);
		expect(geometryFromMember({ ...planet, texture: false })).toMatchObject(drawn);
	});

	it('marks a nominal size as an estimate', () => {
		const moon = { name: 'Kari', id: 'naif-645', radii: { a: 3, b: 3, c: 3 } };
		expect(geometryFromMember(moon)?.sizeEstimated).toBeUndefined();
		const placeholder = {
			...moon,
			radii: { a: 5, b: 5, c: 5, source: 'pck' as const, nominal: true as const }
		};
		expect(geometryFromMember(placeholder)).toMatchObject({ radiusKm: 5, sizeEstimated: true });
	});

	it('sizes an exoplanet with no measured radius by its estimate', () => {
		const planet = { name: 'Proxima Centauri b', id: 'x-27424668-b-1', texture: true };
		expect(geometryFromMember(planet)).toBeNull();
		expect(geometryFromMember({ ...planet, estimated_diameter_km: 13050 })).toMatchObject({
			radiusKm: 6525,
			sizeEstimated: true,
			lunarWeightScale: 0
		});
	});
});

describe('craftGeometryFromMember', () => {
	const mro = { name: 'MRO', id: 'probe-1', model: 'mars-reconnaissance-orbiter', length_m: 13.6 };

	it('sizes a craft at half its span, in km', () => {
		// The convention the main scene uses, so one lineup can hold both kinds.
		expect(craftGeometryFromMember(mro)).toEqual({
			radiusKm: 0.0068,
			meshSpanRatio: 1,
			model: 'mars-reconnaissance-orbiter',
			craft: true
		});
	});

	it('places a boom craft on its body and draws it on its full span', () => {
		// Ulysses is mostly wire dipole; sizing its slot on that would read as a
		// craft ten times the one that flew.
		const ulysses = { name: 'Ulysses', id: 'probe-2', model: 'ulysses', length_m: 63.1 };
		expect(craftGeometryFromMember({ ...ulysses, body_length_m: 2.04 })).toEqual({
			radiusKm: 0.00102,
			meshSpanRatio: 63.1 / 2.04,
			model: 'ulysses',
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

describe('starGeometryFromMember', () => {
	const radii = { a: 5e8, b: 5e8, c: 5e8 };
	const star = { name: 'Betelgeuse', id: 'x-22821649', radii };

	it('takes the temperature first, then the colour', () => {
		const teff = starGeometryFromMember({ ...star, teff: 3600, bp_rp: 0 });
		expect(teff).toMatchObject({ radiusKm: 5e8, photosphere: { teff: 3600 } });
		const colour = starGeometryFromMember({ ...star, bp_rp: 2.5 });
		expect(colour?.photosphere?.teff).toBeLessThan(4000);
	});

	it('leaves out a star with no size or no colour', () => {
		expect(starGeometryFromMember({ ...star, radii: undefined, teff: 3600 })).toBeNull();
		expect(starGeometryFromMember(star)).toBeNull();
	});

	it('draws the Sun as a star in any row', () => {
		const sun = { name: 'Sun', id: 'naif-10', radii: { a: 695700, b: 695700, c: 695700 } };
		expect(starGeometryFromMember(sun)?.photosphere).toEqual({ teff: 5772 });
		expect(geometryFromMember(sun)?.photosphere).toEqual({ teff: 5772 });
	});
});
