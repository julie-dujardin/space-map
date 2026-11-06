/**
 * The block of a star's interior: the curated block as it is, and a fitted
 * row turned into zones at the star's radius, for each tier and kind of star.
 */

import { describe, expect, it } from 'vitest';
import type { Fitted, StarInterior } from '$lib/fetch/extrasolar/interior';
import type { InteriorBlock } from '$lib/fetch/objects/object-data';
import { crossSection } from './interior-cross-section';
import { starInteriorBlock } from './star-interior';
import { SOLAR_RADIUS_KM } from '$lib/math/units';

const R = 1_000_000;
const NONE: Fitted = { value: null, range: null };

function fitted(over: Partial<StarInterior>): StarInterior {
	return {
		id: 1,
		tier: 1,
		curated: null,
		stage: 'main_sequence',
		feh: 0,
		fehSource: 'pastel-2020',
		teff: 5800,
		teffSource: 'gaia-dr3-gspphot',
		luminositySource: 'gaia-dr3-flame',
		mass: { value: 1, range: [0.9, 1.1] },
		radius: { value: 1, range: [0.95, 1.05] },
		envelopeBaseRadius: { value: 0.7, range: [0.65, 0.75] },
		envelopeBaseMass: { value: 0.975, range: [0.97, 0.98] },
		convectiveCoreMass: [0, 0.004],
		heliumCoreMass: [0, 0],
		centreTemperature: { value: 1.6e7, range: [1.5e7, 1.7e7] },
		centreDensity: { value: 150, range: [100, 200] },
		centreX: [0.3, 0.5],
		centreY: [0.5, 0.7],
		...over
	};
}

function roles(block: InteriorBlock | null): string[] {
	return block?.layers?.map((layer) => layer.role) ?? [];
}

describe('a curated interior', () => {
	it('is the paper block, layers with no top or composition kept', () => {
		const curated: InteriorBlock = {
			structure: 'fluid',
			layers: [
				{ role: 'radiative_zone', outer_radius_km: 7e6, composition: [] },
				{ role: 'convective_core', composition: [] }
			]
		};
		const interior = fitted({ tier: 0, curated, mass: NONE, envelopeBaseRadius: NONE });
		expect(starInteriorBlock(interior, null)).toBe(curated);
		expect(starInteriorBlock(interior, R)).toBe(curated);
	});
});

describe('a fitted interior', () => {
	it('is a convective zone over a radiative zone, with the base as a range', () => {
		const block = starInteriorBlock(fitted({}), R)!;
		expect(roles(block)).toEqual(['convective_zone', 'radiative_zone']);
		const [envelope, radiative] = block.layers!;
		expect(envelope.outer_radius_km).toBe(R);
		expect(envelope.mass_fraction).toBeCloseTo(0.025, 6);
		expect(envelope.mass_fraction_range![0]).toBeCloseTo(0.02, 6);
		expect(envelope.mass_fraction_range![1]).toBeCloseTo(0.03, 6);
		expect(radiative.outer_radius_km).toBeCloseTo(0.7 * R, 3);
		expect(radiative.outer_radius_range_km![0]).toBeCloseTo(0.65 * R, 3);
		expect(radiative.outer_radius_range_km![1]).toBeCloseTo(0.75 * R, 3);
		expect(block.layers!.every((layer) => layer.state === 'plasma')).toBe(true);
	});

	it('gives the centre of tiers 1 and 2 as ranges, the temperature with its value', () => {
		const block = starInteriorBlock(fitted({ tier: 2 }), R)!;
		expect(block.centre_temperature_k).toBe(1.6e7);
		expect(block.centre_temperature_range_k).toEqual([1.5e7, 1.7e7]);
		expect(block.centre_density_range_g_cm3).toEqual([100, 200]);
		expect(block.centre_composition).toEqual([
			{ material: 'hydrogen', share_range: [0.3, 0.5] },
			{ material: 'helium', share_range: [0.5, 0.7] }
		]);
	});

	it('gives no centre on tier 3, where the export has none', () => {
		const block = starInteriorBlock(
			fitted({
				tier: 3,
				fehSource: 'assumed-solar',
				centreTemperature: NONE,
				centreDensity: NONE,
				centreX: null,
				centreY: null
			}),
			R
		)!;
		expect(roles(block)).toEqual(['convective_zone', 'radiative_zone']);
		expect(block.centre_temperature_k).toBeUndefined();
		expect(block.centre_temperature_range_k).toBeUndefined();
		expect(block.centre_density_range_g_cm3).toBeUndefined();
		expect(block.centre_composition).toBeUndefined();
	});

	it('is one convective zone for a star convective throughout', () => {
		const block = starInteriorBlock(
			fitted({
				mass: { value: 0.125, range: [0.125, 0.125] },
				envelopeBaseRadius: { value: 0, range: [0, 0.004] },
				envelopeBaseMass: { value: 0, range: [0, 0] },
				convectiveCoreMass: [0.125, 0.125]
			}),
			R
		)!;
		expect(block.layers).toEqual([
			{ role: 'convective_zone', outer_radius_km: R, state: 'plasma', composition: [] }
		]);
	});

	it('has a convective core with a mass range and no top, where the range excludes none', () => {
		const block = starInteriorBlock(
			fitted({ mass: { value: 2, range: [1.8, 2.2] }, convectiveCoreMass: [0.2, 0.4] }),
			R
		)!;
		expect(roles(block)).toEqual(['convective_zone', 'radiative_zone', 'convective_core']);
		const core = block.layers![2];
		expect(core.outer_radius_km).toBeUndefined();
		expect(core.mass_fraction).toBeUndefined();
		expect(core.mass_fraction_range).toEqual([0.1, 0.2]);
	});

	it('draws no core where the core mass can be 0', () => {
		expect(roles(starInteriorBlock(fitted({ convectiveCoreMass: [0, 0.05] }), R))).not.toContain(
			'convective_core'
		);
	});

	it('keeps the thin surface zone of a hot star, and drops it when the base is at the surface', () => {
		const thin = starInteriorBlock(
			fitted({
				envelopeBaseRadius: { value: 0.996, range: [0.996, 0.996] },
				envelopeBaseMass: { value: 1, range: [1, 1] }
			}),
			R
		)!;
		expect(roles(thin)).toEqual(['convective_zone', 'radiative_zone']);
		// A mass share that rounds to 0 is under the rounding, not none.
		expect(thin.layers![0].mass_fraction).toBeUndefined();
		expect(thin.layers![0].mass_fraction_range).toBeUndefined();
		const section = crossSection(thin.layers!)!;
		expect(section.bands[0].thicknessKm).toBeCloseTo(0.004 * R, 3);

		const none = starInteriorBlock(fitted({ envelopeBaseRadius: { value: 1, range: [1, 1] } }), R)!;
		expect(roles(none)).toEqual(['radiative_zone']);
		expect(none.layers![0].outer_radius_km).toBe(R);
	});

	it("takes the fit's radius where the star has none, and none without either", () => {
		const own = starInteriorBlock(fitted({}), R)!;
		expect(own.layers![0].outer_radius_km).toBe(R);
		for (const missing of [null, 0]) {
			const block = starInteriorBlock(fitted({}), missing)!;
			expect(block.layers![0].outer_radius_km).toBe(SOLAR_RADIUS_KM);
			expect(starInteriorBlock(fitted({ radius: NONE }), missing)).toBeNull();
		}
	});
});

describe('the cross-section of a fitted star', () => {
	it('gives thicknesses as ranges, and none where the core has no top', () => {
		const block = starInteriorBlock(
			fitted({ mass: { value: 2, range: [1.8, 2.2] }, convectiveCoreMass: [0.2, 0.4] }),
			R
		)!;
		const [envelope, radiative, core] = crossSection(block.layers!)!.bands;
		expect(envelope.thicknessRangeKm![0]).toBeCloseTo(0.25 * R, 3);
		expect(envelope.thicknessRangeKm![1]).toBeCloseTo(0.35 * R, 3);
		expect(radiative.outerRange![0]).toBeCloseTo(0.65, 6);
		expect(radiative.outerRange![1]).toBeCloseTo(0.75, 6);
		// Its floor is the core's top, which the fit does not give.
		expect(radiative.thicknessKm).toBeNull();
		expect(radiative.depthToKm).toBeNull();
		expect(core.unbounded).toBe(true);
		expect(core.thicknessKm).toBeNull();
		expect(core.outer).toBeCloseTo(0.7, 6);
		expect(core.inner).toBe(0);
	});
});
