/**
 * How the travel panel writes its own quantities: Δv, acceleration, speed,
 * dose, trip dates, and the two clocks of a trip between stars. The rounding
 * rules are here, so that tests can check them. General durations are in
 * `$lib/format/duration`.
 */

import { ltrIsolate } from '$lib/format/bidi';
import { formatJulianDate } from '$lib/format/date';
import { formatKm, formatKmRange } from '$lib/format/distance';
import { formatDurationNarrow, formatSignedDuration } from '$lib/format/duration';
import {
	digitsUnderHundred,
	fixed,
	joinParts,
	joinPartsNoBreak,
	scientificNotation,
	sigFigures,
	type Parts
} from '$lib/format/quantities';
import { sievertParts } from '$lib/format/radiation';
import { G0_M_S2 } from '$lib/math/travel/constants';
import type { EndOrbit } from '$lib/math/travel/maneuvers';
import { LIGHT_YEAR_KM, SPEED_OF_LIGHT_KM_S } from '$lib/math/units';
import * as m from '$lib/paraglide/messages.js';
import { jdToDate } from '$lib/time/jd';

/** A torch drive's budget runs to six figures of km/s, which fits nowhere it
 *  is printed; from here the unit climbs to Mm/s. */
const MEGAMETRE_FLOOR_KMS = 10_000;

/** Three significant figures for the climbed unit — 62.5, 125, 1250. */
function megametres(kms: number): string {
	return sigFigures(kms / 1000, 3);
}

/** True when a Δv is c or more. A held drive spends c × its rapidity, which
 *  passes c on a trip between stars. */
export function isPastLight(kms: number): boolean {
	return kms >= SPEED_OF_LIGHT_KM_S;
}

/** Figure and unit apart, for a stat tile. `decimals` applies to km/s only.
 *  The unit goes up to Mm/s, then to multiples of c. */
function dvPartsAt(kms: number, decimals: number): Parts {
	if (!Number.isFinite(kms)) return { value: '—', unit: '' };
	if (isPastLight(kms)) {
		return { value: sigFigures(kms / SPEED_OF_LIGHT_KM_S, 3), unit: m.symbol_speed_of_light() };
	}
	if (kms >= MEGAMETRE_FLOOR_KMS) {
		return { value: megametres(kms), unit: m.symbol_megametre_per_second() };
	}
	return { value: fixed(kms, decimals), unit: m.symbol_kilometre_per_second() };
}

/** One decimal, which is what a tile and a route row have room for. */
export function dvParts(kms: number): Parts {
	return dvPartsAt(kms, 1);
}

/** The figure alone, two decimals, always km/s — for a diagram that says the
 *  unit once, beside its totals. The Mm/s climb is deliberately not taken: a
 *  bare figure at another scale would read against the unit printed elsewhere. */
export function formatDvFigure(kms: number): string {
	return Number.isFinite(kms) ? fixed(kms, 2) : '—';
}

/** Δv with two decimals — the precision the estimates actually carry. */
export function formatDv(kms: number): string {
	return joinParts(dvPartsAt(kms, 2));
}

/** The route row's tighter form: one decimal, same unit climb. */
export function formatDvBrief(kms: number): string {
	return joinParts(dvParts(kms));
}

/** Two significant figures. The dose models are not more accurate than that. */
function doseFigure(value: number): string {
	return sigFigures(value, 2);
}

/** From this dose the figure has an exponent. Below it the figure has at most
 *  two groups of digits, which the reader takes in at a glance. */
const SCIENTIFIC_FLOOR_SV = 1e6;

/**
 * A dose equivalent. A week in low Earth orbit is a few mSv and the gas of a
 * crossing at 0.95 c is 10⁸ Sv, so the unit takes a prefix and the largest
 * figures take an exponent. The exponent form is in an isolate: without one,
 * right-to-left text puts "10⁸" before its mantissa.
 */
export function formatSievert(sv: number): string {
	if (!Number.isFinite(sv)) return '—';
	if (Number(sv.toPrecision(2)) >= SCIENTIFIC_FLOOR_SV) {
		return ltrIsolate(
			joinPartsNoBreak({ value: scientificNotation(sv, 2), unit: m.symbol_sievert() })
		);
	}
	return joinParts(sievertParts(sv, doseFigure));
}

/** An absorbed dose, in grays. Only belts produce these, in quantities that
 *  need the kilogray — Pioneer 10 took 4.5 of them past Jupiter. */
export function formatGray(gy: number): string {
	if (!Number.isFinite(gy)) return '—';
	if (gy >= 1000) return joinParts({ value: doseFigure(gy / 1000), unit: m.symbol_kilogray() });
	return joinParts({ value: doseFigure(gy), unit: m.symbol_gray() });
}

/** An end orbit as the height it is flown at: one figure when circular, low
 *  point by high point when not. Height above the surface, not distance from
 *  the centre — the only form in which 200 km means the same thing at Earth
 *  and at Mars. */
export function formatEndOrbit(orbit: EndOrbit, bodyRadiusKm: number): string {
	const peri = Math.max(0, orbit.rPeriKm - bodyRadiusKm);
	const apo = Math.max(0, orbit.rApoKm - bodyRadiusKm);
	return apo > peri ? formatKmRange(peri, apo) : formatKm(peri);
}

/** Below this a multiple of a gravity is four leading zeros and no meaning. An
 *  ion drive is a hundredth of this, and reads better in its own unit. */
const GRAVITIES_FLOOR = 0.01;
/** And below this so is m/s². An ion drive's own unit is the millionth: Dawn
 *  held 76 of them, which is a figure, where 0.000076 is a place to count zeros. */
const METRES_FLOOR_MS2 = 1e-3;

/** Two significant figures, which is all any of these are known to. */
function significant(value: number): string {
	return sigFigures(value, 2);
}

/** The acceleration a drive holds, split from its unit for the tile that sets
 *  its own type. Three units, each covering drives the other two cannot say
 *  anything legible about. */
export function accelerationParts(accelMs2: number): Parts {
	if (!Number.isFinite(accelMs2) || accelMs2 <= 0) return { value: '—', unit: '' };
	const gravities = accelMs2 / G0_M_S2;
	if (gravities >= GRAVITIES_FLOOR) {
		return { value: significant(gravities), unit: m.symbol_standard_gravity() };
	}
	if (accelMs2 >= METRES_FLOOR_MS2) {
		return { value: significant(accelMs2), unit: m.unit_symbol_metres_per_second_squared() };
	}
	return { value: significant(accelMs2 * 1e6), unit: m.symbol_micrometre_per_square_second() };
}

/** The same figure as one string, for the places that run it into a line. */
export function formatAcceleration(accelMs2: number): string {
	return joinParts(accelerationParts(accelMs2));
}

/** Below a hundredth of c the fraction is noise; above it, km/s is the noise —
 *  nobody can place 6,500 km/s, and "2.2% c" is the same fact placed. */
const LIGHT_FRACTION_FLOOR = 0.01;

/** The most significant figures a percentage of c takes. */
const LIGHT_PERCENT_MAX_DIGITS = 12;

/** The speed as a percentage of c from 1% of c, else null. Below c, the figure
 *  stays under 100. */
export function lightPercent(kms: number): string | null {
	if (!Number.isFinite(kms)) return null;
	const percent = (kms / SPEED_OF_LIGHT_KM_S) * 100;
	if (percent < LIGHT_FRACTION_FLOOR * 100) return null;
	return sigFigures(percent, digitsUnderHundred(percent, LIGHT_PERCENT_MAX_DIGITS));
}

/** A speed a craft is actually doing: km/s until it is a real fraction of c. */
export function formatSpeed(kms: number): string {
	const percent = lightPercent(kms);
	return percent !== null ? m.travel_unit_percent_c({ value: percent }) : formatDv(kms);
}

/**
 * A date of a trip. A date past the range of `Date` (year 275,760) reads as
 * whole years after `fromJd`, the departure.
 */
export function formatTripDate(jd: number, fromJd: number): string {
	if (Number.isFinite(jdToDate(jd).getTime())) return formatJulianDate(jd);
	return formatSignedDuration(jd - fromJd);
}

/** The ship's clock over a stretch of `days` on the Earth's clock, or null
 *  where the two read the same. */
export function shipDuration(days: number, shipDays: number | undefined): string | null {
	if (shipDays === undefined) return null;
	const ship = formatDurationNarrow(shipDays);
	return ship === formatDurationNarrow(days) ? null : ship;
}

/** A Lorentz factor: two decimals below 10, three significant figures above. */
export function formatLorentzFactor(gamma: number): string {
	if (!Number.isFinite(gamma)) return '—';
	return gamma < 10 ? fixed(gamma, 2) : sigFigures(gamma, 3);
}

/** A distance between stars in light years, figure and unit apart. */
export function lightYearParts(km: number): Parts {
	if (!Number.isFinite(km)) return { value: '—', unit: '' };
	return { value: sigFigures(km / LIGHT_YEAR_KM, 3), unit: m.symbol_light_year() };
}
