/**
 * The ring system's own figures, formatted once for both places that show
 * them: the Rings tab's stat cards and the Overview section's rows.
 */

import type { RingMass } from '$lib/fetch/objects/object-data';
import { convertMass } from '$lib/format/mass';
import { formatNumber, formatUnit } from '$lib/format/quantities';

/** Mass with the hedges its source published.
 *
 * Symbols rather than unit names ("15.4 Zg"): a third of the drawer is not
 * wide enough for "15.4 zettagrams". The note carries the published ± and
 * nothing else — every other hedge is already in the value.
 */
export function formatRingMass(mass: RingMass): {
	/** The figure and its qualifier, without the unit — the Overview hangs the
	 *  ± off this alone, since the unit is not what the ± is about. */
	number: string;
	unit: string;
	note?: string;
} {
	// The upper bound picks the unit and the lower end is expressed in it: a
	// range whose ends chose their own units is two quantities, not one.
	const reference = mass.high_kg ?? mass.low_kg;
	const scaled = convertMass(reference);
	const perKg = reference / scaled.value;
	const unit = formatUnit(scaled.unit, true);
	const inUnit = (kg: number) => formatNumber(kg / perKg);

	// Same grammar as `formatOpticalDepth`, the other hedged number in the
	// panel: a bound reads "< x", a range needs no hedge of its own, and a
	// single figure the source rounded to the decade carries "≈".
	const low = inUnit(mass.low_kg);
	const number = mass.upper_limit
		? `< ${low}`
		: mass.high_kg !== undefined
			? `${low}–${inUnit(mass.high_kg)}`
			: mass.approximate
				? `≈ ${low}`
				: low;

	const note =
		mass.uncertainty_kg !== undefined ? `± ${inUnit(mass.uncertainty_kg)} ${unit}` : undefined;
	return { number, unit, note };
}
