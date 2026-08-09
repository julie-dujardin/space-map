/**
 * Presentation helpers for the travel panel's own quantities — Δv,
 * acceleration, speed. Kept out of the components so the rounding rules are
 * testable and stated once. Durations live in `$lib/format/duration`.
 */

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

/** Standard gravity, m/s² — the unit every torch drive in fiction is quoted in. */
const G0_M_S2 = 9.80665;
/** Below this a multiple of a gravity is four leading zeros and no meaning. An
 *  ion drive is a hundredth of this, and reads better in its own unit. */
const GRAVITIES_FLOOR = 0.01;

/** Two significant figures, which is all any of these are known to. */
function significant(value: number): string {
	return Number(value.toPrecision(2)).toString();
}

/**
 * The acceleration a drive holds, in the unit that makes it mean something: a
 * fraction of a gravity for anything you could stand up in, m/s² for the slow
 * drives where that fraction stops being a number anyone can picture.
 */
export function formatAcceleration(accelMs2: number): string {
	if (!Number.isFinite(accelMs2) || accelMs2 <= 0) return '—';
	const gravities = accelMs2 / G0_M_S2;
	if (gravities < GRAVITIES_FLOOR) {
		return `${significant(accelMs2)} ${m.unit_symbol_metres_per_second_squared()}`;
	}
	return m.travel_unit_g({ value: significant(gravities) });
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
