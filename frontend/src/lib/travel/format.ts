/**
 * Presentation helpers for the travel panel's own quantities — Δv,
 * acceleration, speed. Kept out of the components so the rounding rules are
 * testable and stated once. Durations live in `$lib/format/duration`.
 */

import { formatKm, formatKmRange } from '$lib/format/distance';
import { joinParts, sigFigures, type Parts } from '$lib/format/quantities';
import { sievertParts } from '$lib/format/radiation';
import type { EndOrbit } from '$lib/math/travel/maneuvers';
import * as m from '$lib/paraglide/messages.js';
import { getLocale } from '$lib/paraglide/runtime.js';

/** A torch drive's budget runs to six figures of km/s, which fits nowhere it
 *  is printed; from here the unit climbs to Mm/s. */
const MEGAMETRE_FLOOR_KMS = 10_000;

/** Three significant figures for the climbed unit — 62.5, 125, 1250. */
function megametres(kms: number): string {
	return sigFigures(kms / 1000, 3);
}

/** The locale's own decimals at a stated precision — toFixed would print dot
 *  decimals into the comma locales. */
function fixed(value: number, digits: number): string {
	return value.toLocaleString(getLocale(), {
		minimumFractionDigits: digits,
		maximumFractionDigits: digits
	});
}

/** Figure and unit split apart, for the stat tile that sets its own type.
 *  `decimals` is what separates the panel's Δv from the route row's tighter
 *  one; the unit and the floor it climbs at are shared. */
function dvPartsAt(kms: number, decimals: number): Parts {
	if (!Number.isFinite(kms)) return { value: '—', unit: '' };
	if (kms >= MEGAMETRE_FLOOR_KMS) {
		return { value: megametres(kms), unit: m.symbol_megametre_per_second() };
	}
	return { value: fixed(kms, decimals), unit: m.symbol_kilometre_per_second() };
}

/** One decimal, which is what a tile and a route row have room for. */
export function dvParts(kms: number): Parts {
	return dvPartsAt(kms, 1);
}

/** Δv with two decimals — the precision the estimates actually carry. */
export function formatDv(kms: number): string {
	return joinParts(dvPartsAt(kms, 2));
}

/** The route row's tighter form: one decimal, same unit climb. */
export function formatDvBrief(kms: number): string {
	return joinParts(dvParts(kms));
}

/** Two significant figures. Nothing about a dose is known to more — the cosmic
 *  ray model is good to a few percent and the belt one to a factor of four. */
function doseFigure(value: number): string {
	return Number(value.toPrecision(2)).toString();
}

/** A dose equivalent, in whichever sievert keeps it readable — a week in low
 *  Earth orbit is a few mSv, a slow crossing to Saturn several Sv, so no single
 *  unit serves both. */
export function formatSievert(sv: number): string {
	if (!Number.isFinite(sv)) return '—';
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
