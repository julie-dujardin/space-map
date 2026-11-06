/**
 * The interior block of a star, from its Interior row, in the shape that a
 * body's bundle carries. So the Structure tab draws a star as it draws the Sun.
 *
 * A tier-0 row holds the paper's block, which is used as it is. A fitted row
 * gives fractions of the star's radius and mass. The radius is the star's
 * own, else the fit's. The block puts the outer
 * convective zone from the surface to the envelope base, the radiative zone
 * below it, and a convective core where the fit gives one. The fit gives a
 * core mass and no core radius, so the core has no top. A star convective
 * throughout is one convective zone.
 */

import type { InteriorBlock, InteriorLayer } from '$lib/fetch/objects/object-data';
import type { Fitted, StarInterior } from '$lib/fetch/extrasolar/interior';
import { SOLAR_RADIUS_KM } from '$lib/math/units';

const PLASMA = 'plasma';

/** The block to draw at the star's radius `starKm`, or null where neither the
 *  star nor the fit gives a radius. */
export function starInteriorBlock(
	interior: StarInterior,
	starKm: number | null
): InteriorBlock | null {
	if (interior.curated) return interior.curated;
	const fitKm = interior.radius.value === null ? null : interior.radius.value * SOLAR_RADIUS_KM;
	const radiusKm = starKm !== null && starKm > 0 ? starKm : fitKm;
	if (radiusKm === null || !(radiusKm > 0)) return null;
	const block: InteriorBlock = { structure: 'fluid', layers: fittedLayers(interior, radiusKm) };
	const { centreTemperature: t, centreDensity: rho } = interior;
	if (t.value !== null) block.centre_temperature_k = t.value;
	if (t.range) block.centre_temperature_range_k = t.range;
	if (rho.value !== null) block.centre_density_g_cm3 = rho.value;
	if (rho.range) block.centre_density_range_g_cm3 = rho.range;
	if (interior.centreX) block.centre_hydrogen_range = interior.centreX;
	if (interior.centreY) block.centre_helium_range = interior.centreY;
	return block;
}

function fittedLayers(interior: StarInterior, radiusKm: number): InteriorLayer[] {
	const base = interior.envelopeBaseRadius;
	const surface: InteriorLayer = {
		role: 'convective_zone',
		outer_radius_km: radiusKm,
		state: PLASMA,
		composition: []
	};
	if (base.value === null || base.value <= 0) return [surface];

	const layers: InteriorLayer[] = [];
	// A base at the surface on every side of the range leaves no zone to draw.
	if (!(base.range ? base.range[0] >= 1 : base.value >= 1)) {
		layers.push({ ...surface, ...envelopeMass(interior.envelopeBaseMass) });
	}
	const radiative: InteriorLayer = {
		role: 'radiative_zone',
		outer_radius_km: base.value * radiusKm,
		state: PLASMA,
		composition: []
	};
	if (base.range) {
		radiative.outer_radius_range_km = [base.range[0] * radiusKm, base.range[1] * radiusKm];
	}
	layers.push(radiative);

	// A range that reaches 0 does not say that the star has a core.
	const core = interior.convectiveCoreMass;
	const mass = interior.mass.value;
	if (core && core[0] > 0 && mass !== null && mass > 0) {
		layers.push({
			role: 'convective_core',
			state: PLASMA,
			mass_fraction_range: [core[0] / mass, Math.min(core[1] / mass, 1)],
			composition: []
		});
	}
	return layers;
}

type LayerMass = Pick<InteriorLayer, 'mass_fraction' | 'mass_fraction_range'>;

/** The share of the star's mass above the envelope base. A share that rounds
 *  to 0 is under the rounding, not none, so it gives its range alone. */
function envelopeMass(base: Fitted): LayerMass {
	if (base.value === null) return {};
	const range: [number, number] | undefined = base.range
		? [1 - base.range[1], 1 - base.range[0]]
		: undefined;
	const share = 1 - base.value;
	if (share > 0)
		return range ? { mass_fraction: share, mass_fraction_range: range } : { mass_fraction: share };
	return range && range[1] > 0 ? { mass_fraction_range: range } : {};
}
