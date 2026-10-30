/**
 * The interstellar dust that a craft meets between two stars.
 *
 * The model is the number of grains per m³ in each bin of radius, for grains of
 * 3 g/cm³. The bins hold the grains at the Sun and scale with the density of the
 * gas along a crossing. The dust moves at about 26 km/s against the Sun. The
 * model takes it to be at rest, so the grains that hit one m² of frontal area
 * are the density times the distance. This holds well near the speed of light,
 * and only roughly on a coast of tens of km/s.
 *
 * - Below 0.3 µm: the model of Weingartner & Draine 2001 (ApJ 548, 296),
 *   Table 1, R_V = 3.1, b_C = 6 × 10⁻⁵. The heliosphere keeps these grains away
 *   from the Sun, so no measurement shows them.
 * - 0.3 to 3 µm: Ulysses, Krüger et al. 2015 (ApJ 812, 139), Table 5. Its
 *   cumulative flux over the inflow speed of 26 km/s (Krüger et al. 2019,
 *   A&A 626, A37) is a density.
 * - Above 3 µm: the cumulative flux falls as the mass to the power −1.1
 *   (Landgraf et al. 2000, JGR 105, 10343, §5). Few grains of these sizes were
 *   measured, so this is an extrapolation.
 *
 * In a bin, the number of grains above a radius is a power law of the radius
 * through the values at the two edges of the bin.
 */

import { INTERSTELLAR_N_H_CM3 } from './gas';

const MICRON_M = 1e-6;

/** Mass per volume of one grain, kg/m³. */
const GRAIN_DENSITY_KG_M3 = 3000;

/** Grains per m³ with a radius between `fromUm` and `toUm`, µm. */
interface SizeBin {
	fromUm: number;
	toUm: number;
	perM3: number;
}

const SIZE_BINS: readonly SizeBin[] = [
	// Weingartner & Draine 2001.
	{ fromUm: 0.01, toUm: 0.03, perM3: 6.5e-6 },
	{ fromUm: 0.03, toUm: 0.1, perM3: 6.49e-7 },
	{ fromUm: 0.1, toUm: 0.3, perM3: 4.91e-8 },
	// Krüger et al. 2015, Table 5.
	{ fromUm: 0.3, toUm: 1, perM3: 7.83e-10 },
	// Table 5 above 1 µm, less the extrapolated grains above 3 µm.
	{ fromUm: 1, toUm: 3, perM3: 2.98e-11 }
];

/** The cumulative flux of Landgraf et al. 2000: 10⁻⁶ grains per m² per second
 *  above 10⁻¹⁴ kg. */
const TAIL_FLUX_M2_S = 1e-6;
const TAIL_MASS_KG = 1e-14;
const TAIL_MASS_SLOPE = 1.1;

/** Hydrogen nuclei per cm³ at the Sun, neutral and ionized (Slavin & Frisch
 *  2008). The bins are for this density. */
const SUN_N_H_CM3 = 0.25;

/** The grains scale with the gas at a fixed ratio of dust to gas (WD01 give them
 *  per H nucleon). */
const GAS_SCALE = INTERSTELLAR_N_H_CM3 / SUN_N_H_CM3;

/** Speed of the dust against the Sun, m/s. */
const INFLOW_M_S = 26e3;

/** Radius above which the sizes are extrapolated, m. */
export const MEASURED_GRAIN_RADIUS_M = SIZE_BINS[SIZE_BINS.length - 1].toUm * MICRON_M;

export function grainMassKg(radiusM: number): number {
	return (4 / 3) * Math.PI * radiusM ** 3 * GRAIN_DENSITY_KG_M3;
}

function tailAbove(radiusM: number): number {
	return (TAIL_FLUX_M2_S / INFLOW_M_S) * (grainMassKg(radiusM) / TAIL_MASS_KG) ** -TAIL_MASS_SLOPE;
}

/** A power law of the number of grains above a radius: `perM3` above `fromM`,
 *  falling as the radius to the power −`slope`, up to `toM`. */
interface Segment {
	fromM: number;
	toM: number;
	perM3: number;
	slope: number;
}

const SEGMENTS: readonly Segment[] = (() => {
	const tail: Segment = {
		fromM: MEASURED_GRAIN_RADIUS_M,
		toM: Infinity,
		perM3: tailAbove(MEASURED_GRAIN_RADIUS_M),
		slope: 3 * TAIL_MASS_SLOPE
	};
	const out: Segment[] = [tail];
	for (let i = SIZE_BINS.length - 1; i >= 0; i--) {
		const { fromUm, toUm, perM3 } = SIZE_BINS[i];
		const above = out[0].perM3;
		out.unshift({
			fromM: fromUm * MICRON_M,
			toM: toUm * MICRON_M,
			perM3: perM3 + above,
			slope: Math.log((perM3 + above) / above) / Math.log(toUm / fromUm)
		});
	}
	return out.map((segment) => ({ ...segment, perM3: segment.perM3 * GAS_SCALE }));
})();

/** Grains per m³ with a radius above `radiusM`. Below the first bin, the first
 *  bin's power law continues. */
export function grainsAbove(radiusM: number): number {
	const segment = SEGMENTS.findLast((s) => s.fromM <= radiusM) ?? SEGMENTS[0];
	return segment.perM3 * (radiusM / segment.fromM) ** -segment.slope;
}

/** Radius of the largest grain expected to hit one m² over `distanceKm`, m. It
 *  is the radius where the expected number of hits is one. */
export function largestGrainRadiusM(distanceKm: number): number {
	const perM3 = 1 / (distanceKm * 1000);
	const segment = SEGMENTS.findLast((s) => s.perM3 >= perM3) ?? SEGMENTS[0];
	return segment.fromM * (segment.perM3 / perM3) ** (1 / segment.slope);
}

/** Mass of the grains of one segment per m³, kg. */
function segmentMassKgM3({ fromM, toM, perM3, slope }: Segment): number {
	const k = 3 - slope;
	const growth = k === 0 ? Math.log(toM / fromM) : Math.expm1(k * Math.log(toM / fromM)) / k;
	return grainMassKg(fromM) * perM3 * slope * growth;
}

/** Mass of all the grains per m³, kg. The tail above 3 µm holds about a third. */
export const DUST_MASS_KG_M3 = SEGMENTS.reduce((sum, s) => sum + segmentMassKgM3(s), 0);
