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

import {
	canDepartFrom,
	checkFeasibility,
	constantThrustAccelMs2,
	dvWithPayloadKms,
	maxPayloadKgForRoute,
	type Manifest,
	type PropulsionKind,
	type Route,
	type Vehicle,
	type VehicleStatus
} from '$lib/math/travel';
import { localName, vehicleNaming } from '$lib/travel/vehicles';
import { formatAcceleration, formatDv } from '$lib/travel/format';
import { formatQuantity } from '$lib/format/quantities';
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

/** Partial on purpose: the catalogue is fetched, so a cached or future export
 *  can carry kinds this build has no words for — a blank beats a crash. */
const PROPULSION_MESSAGES: Partial<Record<PropulsionKind, () => string>> = {
	chemical: m.spacecraft_propulsion_chemical,
	electric: m.spacecraft_propulsion_electric,
	nuclear: m.spacecraft_propulsion_nuclear,
	'solar-sail': m.spacecraft_propulsion_solar_sail,
	fictional: m.spacecraft_propulsion_fictional
};

/** Active is the reader's default assumption, so it is left out of the badges
 *  the picker appends — a spec row asking outright still gets an answer, from
 *  `vehicleStatusLabel`. */
const STATUS_MESSAGES: Partial<Record<VehicleStatus, () => string>> = {
	retired: m.spacecraft_status_retired,
	planned: m.spacecraft_status_planned,
	cancelled: m.spacecraft_status_cancelled,
	concept: m.spacecraft_status_concept,
	fictional: m.spacecraft_status_fictional
};

/** What powers it, for the craft whose source says. Partial for the same reason
 *  as the propulsion table above, and deliberately silent on `fictional`: a
 *  ship the badges already call fiction learns nothing from a third row of it. */
const POWER_MESSAGES: Partial<Record<NonNullable<Vehicle['power']>, () => string>> = {
	solar: m.spacecraft_power_solar,
	rtg: m.spacecraft_power_rtg,
	nuclear: m.spacecraft_power_nuclear,
	battery: m.spacecraft_power_battery
};

export function vehiclePowerLabel(vehicle: Vehicle): string | null {
	return vehicle.power ? (POWER_MESSAGES[vehicle.power]?.() ?? null) : null;
}

export function vehiclePropulsionLabel(vehicle: Vehicle): string | null {
	return PROPULSION_MESSAGES[vehicle.propulsion]?.() ?? null;
}

/** Unlike the badges, this answers for an active craft too: a row headed
 *  "Status" that shows nothing reads as a figure nobody published. */
export function vehicleStatusLabel(vehicle: Vehicle): string | null {
	if (vehicle.status === 'active') return m.spacecraft_status_active();
	return STATUS_MESSAGES[vehicle.status]?.() ?? null;
}

/** "electric", "retired" — what the craft *is*, as against what it can do. Once
 *  each: a fictional drive on a fictional ship is one fact, not two. */
export function vehicleBadgeParts(vehicle: Vehicle): string[] {
	const badges = [PROPULSION_MESSAGES[vehicle.propulsion]?.(), STATUS_MESSAGES[vehicle.status]?.()];
	return [...new Set(badges.filter((badge): badge is string => badge !== undefined))];
}

/**
 * The stat line under a craft: what it can do, then what it is.
 *
 * Against a route, the Δv becomes the margin left after flying it — the raw
 * figure answers "how much", the margin answers the question the reader is
 * actually in the picker with. Craft whose propellant is no constraint show
 * their acceleration instead: their Δv is "yes", and the drive is the number
 * that tells two of them apart. A fictional craft says so once, not once per
 * field.
 */
export function vehicleStatsParts(
	vehicle: Vehicle,
	route: Route | null,
	manifest: Manifest
): string[] {
	const parts: string[] = [];

	if (vehicle.unlimitedDv) {
		const accel = constantThrustAccelMs2(vehicle) ?? vehicle.accelMs2?.value;
		parts.push(accel !== undefined ? formatAcceleration(accel) : m.travel_dv_unlimited());
	} else {
		const margin = route ? checkFeasibility(vehicle, route, manifest).marginKms : NaN;
		const dv = dvWithPayloadKms(vehicle, manifest.payloadKg);
		if (Number.isFinite(margin)) {
			parts.push(m.travel_dv_margin({ value: formatDv(margin) }));
		} else if (dv !== undefined) {
			// A route the impulsive model cannot judge this craft against still
			// leaves the craft's own budget worth saying.
			parts.push(m.travel_stat_dv({ value: formatDv(dv) }));
		}
	}

	if (route) {
		const payloadKg = maxPayloadKgForRoute(vehicle, route);
		if (payloadKg !== null) {
			const value = formatQuantity({ value: Math.round(payloadKg), unit: 'kilogram' }, true);
			parts.push(m.travel_carries({ value }));
		}
	}

	for (const badge of vehicleBadgeParts(vehicle)) {
		if (!parts.includes(badge)) parts.push(badge);
	}
	return parts;
}
