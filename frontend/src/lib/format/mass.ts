import * as m from '$lib/paraglide/messages.js';
import {
	atParity,
	earthRatio,
	formatMeasuredQuantity,
	formatQuantity,
	formatSpan,
	formatUnit,
	joinParts,
	percentParts,
	powerOfTen,
	type MeasuredQuantity,
	type Parts
} from './quantities';

/** So a body's mass can be read against the one anyone has a feel for. */
export const EARTH_MASS_KG = 5.9722e24;
/** IAU nominal Jupiter and solar masses (2015 Resolution B3 GM over G). */
export const JUPITER_MASS_KG = 1.89813e27;
export const SOLAR_MASS_KG = 1.98841e30;

// Mirrors the backend mass ladder (export/quantities.py UnitConverter): the
// SI gram prefixes, sorted by factor (kg) descending.
const MASS_UNITS: { unit: string; kg: number }[] = [
	{ unit: 'ronnagram', kg: 1e24 },
	{ unit: 'yottagram', kg: 1e21 },
	{ unit: 'zettagram', kg: 1e18 },
	{ unit: 'exagram', kg: 1e15 },
	{ unit: 'petagram', kg: 1e12 },
	{ unit: 'teragram', kg: 1e9 },
	{ unit: 'tonne', kg: 1e3 },
	{ unit: 'kilogram', kg: 1 },
	{ unit: 'gram', kg: 1e-3 }
];

/** The astronomical masses the backend also exports in. Read only, never written. */
const EXPORTED_UNITS = [
	{ unit: 'jupiter_mass', kg: JUPITER_MASS_KG },
	{ unit: 'earth_mass', kg: EARTH_MASS_KG },
	...MASS_UNITS
];

// Largest unit whose value reads above ~1, matching the backend's best_unit.
export function convertMass(kg: number): { value: number; unit: string } {
	const abs = Math.abs(kg);
	const u = MASS_UNITS.find((x) => abs / x.kg > 1.1) ?? MASS_UNITS[MASS_UNITS.length - 1];
	return { value: kg / u.kg, unit: u.unit };
}

/** Back to kilograms from whatever unit the source published — the export picks
 *  a unit per body off the same ladder, so neighbours arrive incomparable. */
export function massKg(q: { value: number; unit: string }): number | null {
	const u = EXPORTED_UNITS.find((x) => x.unit === q.unit);
	return u ? q.value * u.kg : null;
}

/**
 * Every body on one unit, in the notation the field quotes mass in.
 *
 * A ladder of prefixed grams reads Earth "5.97 Rg" and Phobos "10.7 Eg", two
 * scales a reader has to convert between. Kilograms and an exponent are the
 * same shape for all of them.
 */
function massParts(kg: number): Parts {
	// Three fixed figures: Jupiter's "1.9" beside Earth's "5.97" reads as less known.
	const value = formatMeasuredQuantity({ value: kg, power: powerOfTen(kg, 3), fixedDecimals: 2 });
	return { value, unit: formatUnit('kilogram', true) };
}

export function formatMass(kg: number): string {
	return joinParts(massParts(kg));
}

/** An exported mass in kilograms, and what it comes to against the Sun,
 *  Jupiter or Earth. A unit with no factor keeps its own. */
export function massReading(q: { value: number; unit: string }): {
	value: string;
	tooltip?: string;
} {
	const kg = massKg(q);
	if (kg === null) return { value: formatQuantity(q) };
	return { value: formatMass(kg), tooltip: massComparison(kg) };
}

export function formatMassRange(loKg: number, hiKg: number): string {
	return formatSpan(massParts(loKg), massParts(hiKg));
}

/** A mass and its errors, all in kilograms, on the value's power of ten. */
export function formatMeasuredMass(q: Omit<MeasuredQuantity, 'unit' | 'power' | 'tight'>): string {
	return formatMeasuredQuantity({
		...q,
		unit: formatUnit('kilogram', true),
		power: powerOfTen(q.value, 3)
	});
}

/** The masses a body's is read against, largest first, and the share of each
 *  from which the figure says something about the body. Earth, the last,
 *  holds down to a hundredth: the Moon. */
const REFERENCES = [
	{ kg: SOLAR_MASS_KG, floor: 0.1, times: m.sun_times, percent: m.sun_percent },
	{ kg: JUPITER_MASS_KG, floor: 0.1, times: m.jupiter_times, percent: m.jupiter_percent },
	{ kg: EARTH_MASS_KG, floor: 0.01, times: m.earth_times, percent: m.earth_percent }
];

/**
 * What a mass comes to against the Sun, Jupiter or Earth, with its errors.
 * Parity is no comparison, so the next reference down makes it: Jupiter is
 * "318× Earth". Undefined under a hundredth of Earth's, where none helps.
 */
export function massComparison(
	kg: number,
	upperError: number | null = null,
	lowerError: number | null = null
): string | undefined {
	const ref = REFERENCES.find((r) => kg / r.kg >= r.floor && !atParity(kg / r.kg));
	if (!ref) return undefined;
	const ratio = kg / ref.kg;
	if (!upperError && !lowerError) return earthRatio(ratio, ref) ?? undefined;
	// A multiple applies to its errors too, so they go in brackets.
	const percent = ratio < 1;
	const scale = (percent ? 100 : 1) / ref.kg;
	const figure = formatMeasuredQuantity({
		value: kg * scale,
		upperError: upperError && upperError * scale,
		lowerError: lowerError && lowerError * scale,
		roundLargeErrors: true,
		...(percent ? { unit: percentParts(0).unit, tight: true } : { group: true })
	});
	return percent ? ref.percent({ value: figure }) : ref.times({ value: figure });
}
