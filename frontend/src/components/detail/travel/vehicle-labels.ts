/**
 * What a craft is called in the picker.
 *
 * Three sources, in order: the per-locale name bundle the pipeline builds from
 * Wikidata labels, a hand-authored message key for the two ships Wikidata has
 * no item for, and the catalogue's English name as a last resort. The slug is
 * never shown — a row reading `atlas-v-551-star-48` is worse than one reading
 * a name in the wrong language.
 *
 * Configuration qualifiers are appended rather than baked into the name: three
 * Falcon Heavy entries share one Wikidata label, and what separates them is
 * ours to translate.
 */

import { canDepartFrom, type Vehicle } from '$lib/math/travel';
import { localName, vehicleNaming } from '$lib/travel/vehicles';
import * as m from '$lib/paraglide/messages.js';

const VARIANT_MESSAGES: Record<string, () => string> = {
	expendable: m.spacecraft_variant_expendable,
	reusable: m.spacecraft_variant_reusable,
	'star-48': m.spacecraft_variant_star_48
};

/** The vehicle's name alone, without what configuration of it this is. */
export function vehicleBaseName(vehicle: Vehicle): string {
	return localName(vehicle) ?? vehicleNaming(vehicle.id)?.name ?? vehicle.name ?? vehicle.id;
}

/** "expendable, Star 48" — empty when the name already identifies the entry. */
export function vehicleVariantLabel(vehicle: Vehicle): string {
	const parts = (vehicle.variant ?? [])
		.map((slug) => VARIANT_MESSAGES[slug]?.() ?? slug)
		.filter(Boolean);
	return parts.join(m.travel_list_separator());
}

export function vehicleName(vehicle: Vehicle): string {
	const variant = vehicleVariantLabel(vehicle);
	const name = vehicleBaseName(vehicle);
	return variant ? m.travel_craft_with_variant({ name, variant }) : name;
}

/**
 * Where this craft can start, said in terms of what it *can* do.
 *
 * Used wherever a craft and a departure disagree — the greyed picker row and
 * the route it cannot fly. "Starts from the ground" is a fact about the SLS;
 * "cannot start here" would be a complaint about the user's origin box.
 */
export function departureNote(vehicle: Vehicle): string {
	if (canDepartFrom(vehicle, 'surface')) return m.travel_craft_from_ground();
	if (canDepartFrom(vehicle, 'orbit')) return m.travel_craft_from_orbit();
	return m.travel_craft_carried();
}

/** Wikidata's one-liner, for the row beneath the name. Absent for many. */
export function vehicleDescription(vehicle: Vehicle): string | null {
	return vehicleNaming(vehicle.id)?.description ?? null;
}
