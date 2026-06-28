import { formatQuantity } from './quantities';

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
