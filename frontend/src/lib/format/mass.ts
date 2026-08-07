import {
	earthRatio,
	formatNumber,
	formatQuantity,
	formatUnit,
	scientificNotation
} from './quantities';

// Mirrors the backend mass ladder (export/quantities.py UnitConverter): the
// astronomical masses it allowlists, then the SI gram prefixes, sorted by factor
// (kg) descending. Only units with a frontend label are listed (no solar mass).
const MASS_UNITS: { unit: string; kg: number }[] = [
	{ unit: 'jupiter_mass', kg: 1.898e27 },
	{ unit: 'earth_mass', kg: 5.9722e24 },
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

// Largest unit whose value reads above ~1, matching the backend's best_unit.
export function convertMass(kg: number): { value: number; unit: string } {
	const abs = Math.abs(kg);
	const u = MASS_UNITS.find((x) => abs / x.kg > 1.1) ?? MASS_UNITS[MASS_UNITS.length - 1];
	return { value: kg / u.kg, unit: u.unit };
}

export function formatMass(kg: number): string {
	return formatQuantity(convertMass(kg));
}

// Both ends in one shared unit (taken from the upper bound) so a range stays
// comparable; without this each end could pick a different unit.
export function formatMassRange(loKg: number, hiKg: number): string {
	const { unit } = convertMass(hiKg);
	const kgPer = MASS_UNITS.find((u) => u.unit === unit)!.kg;
	return `${formatNumber(loKg / kgPer)} – ${formatQuantity({ value: hiKg / kgPer, unit })}`;
}

/** So a body's mass can be read against the one anyone has a feel for. */
export const EARTH_MASS_KG = 5.9722e24;

/** Back to kilograms from whatever unit the source published — the export picks
 *  a unit per body off the same ladder, so neighbours arrive incomparable. */
export function massKg(q: { value: number; unit: string }): number | null {
	const u = MASS_UNITS.find((x) => x.unit === q.unit);
	return u ? q.value * u.kg : null;
}

/**
 * Every body on one unit, in the notation the field actually quotes mass in.
 *
 * The per-body ladder is right for a chart, where the axis carries the unit,
 * and wrong for a stat card standing on its own: Earth reads "5.97 Rg" and
 * Jupiter "318 M⊕", which are three unrelated scales on three neighbouring
 * pages. Kilograms and an exponent are the same shape for all of them.
 */
export function formatMassKg(kg: number): string {
	return `${scientificNotation(kg, 3)} ${formatUnit('kilogram', true)}`;
}

/** What that comes to against Earth, which is the only part of a 25-digit
 *  number anyone can hold. */
export function massEarthNote(kg: number): string | undefined {
	return earthRatio(kg / EARTH_MASS_KG) ?? undefined;
}
