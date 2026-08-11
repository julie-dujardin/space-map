/**
 * Presentation helpers for the travel panel's own quantities — Δv,
 * acceleration, speed. Kept out of the components so the rounding rules are
 * testable and stated once. Durations live in `$lib/format/duration`.
 */

import { formatKm, formatKmRange } from '$lib/format/distance';
import type { EndOrbit } from '$lib/math/travel/maneuvers';
import * as m from '$lib/paraglide/messages.js';

/** A torch drive's budget runs to six figures of km/s, which fits nowhere it
 *  is printed; from here the unit climbs to Mm/s. */
const MEGAMETRE_FLOOR_KMS = 10_000;

/** Three significant figures for the climbed unit — 62.5, 125, 1250. */
function megametres(kms: number): string {
	return Number((kms / 1000).toPrecision(3)).toString();
}

/** Δv with two decimals — the precision the estimates actually carry. */
export function formatDv(kms: number): string {
	if (!Number.isFinite(kms)) return '—';
	if (kms >= MEGAMETRE_FLOOR_KMS) return m.travel_unit_mm_s({ value: megametres(kms) });
	return m.travel_unit_km_s({ value: kms.toFixed(2) });
}

/** The route row's tighter form: one decimal, same unit climb. */
export function formatDvBrief(kms: number): string {
	if (!Number.isFinite(kms)) return '—';
	if (kms >= MEGAMETRE_FLOOR_KMS) return m.travel_unit_mm_s({ value: megametres(kms) });
	return m.travel_unit_km_s({ value: kms.toFixed(1) });
}

/** Figure and unit split apart, for the stat tile that sets its own type. */
export function dvParts(kms: number): { value: string; unit: string } {
	if (!Number.isFinite(kms)) return { value: '—', unit: '' };
	if (kms >= MEGAMETRE_FLOOR_KMS) return { value: megametres(kms), unit: m.travel_mm_s() };
	return { value: kms.toFixed(1), unit: m.travel_km_s() };
}

/** Two significant figures. Nothing about a dose is known to more — the cosmic
 *  ray model is good to a few percent and the belt one to a factor of four. */
function doseFigure(value: number): string {
	return Number(value.toPrecision(2)).toString();
}

/**
 * A dose equivalent, in whichever sievert keeps it readable.
 *
 * The span is enormous and unavoidable: a week in low Earth orbit is a few mSv
 * and a slow crossing to Saturn is several Sv, so no single unit serves both.
 */
export function formatSievert(sv: number): string {
	if (!Number.isFinite(sv)) return '—';
	if (sv >= 1) return m.travel_unit_sv({ value: doseFigure(sv) });
	if (sv >= 1e-3) return m.travel_unit_msv({ value: doseFigure(sv * 1e3) });
	return m.travel_unit_usv({ value: doseFigure(sv * 1e6) });
}

/**
 * An absorbed dose, in grays.
 *
 * Only belts produce these, and they produce them in quantities that need the
 * kilogray — Pioneer 10 took 4.5 of them going past Jupiter.
 */
export function formatGray(gy: number): string {
	if (!Number.isFinite(gy)) return '—';
	if (gy >= 1000) return m.travel_unit_kgy({ value: doseFigure(gy / 1000) });
	return m.travel_unit_gy({ value: doseFigure(gy) });
}

/**
 * An end orbit as the height it is flown at: one figure when it is circular, low
 * point by high point when it is not.
 *
 * Height above the surface rather than distance from the centre, which is how
 * every orbit anyone has flown is quoted, and the only form in which 200 km
 * means the same thing at Earth and at Mars.
 */
export function formatEndOrbit(orbit: EndOrbit, bodyRadiusKm: number): string {
	const peri = Math.max(0, orbit.rPeriKm - bodyRadiusKm);
	const apo = Math.max(0, orbit.rApoKm - bodyRadiusKm);
	// An ellipse is a height that varies, which is what a range says — and says
	// with the unit written once and the separator the locale's own.
	return apo > peri ? formatKmRange(peri, apo) : formatKm(peri);
}

/** Standard gravity, m/s² — the unit every torch drive in fiction is quoted in. */
const G0_M_S2 = 9.80665;
/** Below this a multiple of a gravity is four leading zeros and no meaning. An
 *  ion drive is a hundredth of this, and reads better in its own unit. */
const GRAVITIES_FLOOR = 0.01;
/** And below this so is m/s². An ion drive's own unit is the millionth: Dawn
 *  held 76 of them, which is a figure, where 0.000076 is a place to count zeros. */
const METRES_FLOOR_MS2 = 1e-3;

/** Two significant figures, which is all any of these are known to. */
function significant(value: number): string {
	return Number(value.toPrecision(2)).toString();
}

/**
 * The acceleration a drive holds, split from its unit for the tile that sets its
 * own type. Three units, each covering the drives the other two cannot say
 * anything legible about.
 */
export function accelerationParts(accelMs2: number): { value: string; unit: string } {
	if (!Number.isFinite(accelMs2) || accelMs2 <= 0) return { value: '—', unit: '' };
	const gravities = accelMs2 / G0_M_S2;
	if (gravities >= GRAVITIES_FLOOR) {
		return { value: significant(gravities), unit: m.travel_g() };
	}
	if (accelMs2 >= METRES_FLOOR_MS2) {
		return { value: significant(accelMs2), unit: m.unit_symbol_metres_per_second_squared() };
	}
	return { value: significant(accelMs2 * 1e6), unit: m.travel_um_s2() };
}

/** The same figure as one string, for the places that run it into a line. */
export function formatAcceleration(accelMs2: number): string {
	const { value, unit } = accelerationParts(accelMs2);
	return unit ? `${value} ${unit}` : value;
}

const LIGHT_SPEED_KMS = 299792.458;
/** Below a hundredth of c the fraction is noise; above it, km/s is the noise —
 *  nobody can place 6,500 km/s, and "2.2% c" is the same fact placed. */
const LIGHT_FRACTION_FLOOR = 0.01;

/** The speed as a percentage of c once it is at least 1% of it, else null. */
export function lightPercent(kms: number): string | null {
	if (!Number.isFinite(kms)) return null;
	const fraction = kms / LIGHT_SPEED_KMS;
	return fraction >= LIGHT_FRACTION_FLOOR ? significant(fraction * 100) : null;
}

/** A speed a craft is actually doing: km/s until it is a real fraction of c. */
export function formatSpeed(kms: number): string {
	const percent = lightPercent(kms);
	return percent !== null ? m.travel_unit_percent_c({ value: percent }) : formatDv(kms);
}
