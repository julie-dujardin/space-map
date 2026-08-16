/**
 * The ring system's own figures, formatted once for both places that show
 * them: the Rings tab's stat cards and the Overview section's rows.
 */

import type { RingMass } from '$lib/fetch/objects/object-data';
import { convertMass } from '$lib/format/mass';
import { formatNumber, formatUnit } from '$lib/format/quantities';

/** Mass with the hedges its source published.
 *
 * Symbols not unit names ("15.4 Zg"): the drawer isn't wide enough for
 * "zettagrams". `note` carries only the published ± — every other hedge is
 * already in the value.
 */
export function formatRingMass(mass: RingMass): {
	/** Figure + qualifier, no unit — the Overview hangs the ± off this alone. */
	number: string;
	unit: string;
	note?: string;
} {
	// Upper bound picks the unit; lower end is expressed in it, so a range
	// isn't two quantities with two units.
	const reference = mass.high_kg ?? mass.low_kg;
	const scaled = convertMass(reference);
	const perKg = reference / scaled.value;
	const unit = formatUnit(scaled.unit, true);
	const inUnit = (kg: number) => formatNumber(kg / perKg);

	// Same grammar as formatOpticalDepth: "< x" for a bound, "≈ x" for a
	// rounded single figure, a bare range needs no hedge.
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
