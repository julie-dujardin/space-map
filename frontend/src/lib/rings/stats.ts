/**
 * The ring system's own figures, formatted once for both places that show
 * them: the Rings tab's stat cards and the Overview section's rows.
 */

import type { RingMass } from '$lib/fetch/objects/object-data';
import {
	formatBound,
	formatNumber,
	formatUnit,
	joinParts,
	powerOfTen,
	powerUnit,
	type Parts
} from '$lib/format/quantities';

/** Mass with the hedges its source published, in kilograms and a power of
 *  ten as every body's is ("1.54×10¹⁹ kg"). `note` carries only the
 *  published ± — every other hedge is already in the value.
 */
export function formatRingMass(mass: RingMass): Parts & { note?: string } {
	// The upper end picks the power of ten and the lower end is written on it,
	// so a range isn't two quantities.
	const reference = mass.high_kg ?? mass.low_kg;
	const power = powerOfTen(reference, 3);
	const unit = powerUnit(formatUnit('kilogram', true), power);
	const inUnit = (kg: number) => formatNumber(kg / 10 ** power);

	// Same grammar as formatOpticalDepth: "< x" for a bound, "≈ x" for a
	// rounded single figure, a bare range needs no hedge.
	const low = inUnit(mass.low_kg);
	// The figure carries its own qualifier and no unit: the Overview hangs the
	// published ± off this alone.
	const value = mass.upper_limit
		? formatBound(low)
		: mass.high_kg !== undefined
			? `${low}–${inUnit(mass.high_kg)}`
			: mass.approximate
				? `≈ ${low}`
				: low;

	const note =
		mass.uncertainty_kg !== undefined
			? joinParts({ value: `± ${inUnit(mass.uncertainty_kg)}`, ...unit })
			: undefined;
	return { value, ...unit, note };
}
