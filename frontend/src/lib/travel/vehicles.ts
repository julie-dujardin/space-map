/**
 * Craft you can filter the trajectories by.
 *
 * The catalogue is fetched rather than declared — `/data/v1/spacecraft.json`,
 * built from cited constants in the pipeline. Every figure carries its source
 * key, so a panel showing "Δv 2.80 km/s" can show what that came from and
 * whether it was derived from a mass and an engine or published outright.
 *
 * Loaded on demand rather than at boot: the file is small but nobody who never
 * opens the travel panel needs it.
 */

import {
	loadSpacecraft,
	allVehicles,
	vehicleById,
	sourceCitation,
	vehicleNaming
} from '$lib/fetch/spacecraft';
import type { Vehicle } from '$lib/math/travel';
import * as m from '$lib/paraglide/messages.js';

export { sourceCitation, vehicleNaming };
export type { SourceCitation, VehicleNaming } from '$lib/fetch/spacecraft';

/** Fetch the catalogue if it is not already in memory. Safe to call repeatedly. */
export function ensureVehicles(): Promise<void> {
	return loadSpacecraft();
}

export function vehicleCatalogue(): readonly Vehicle[] {
	return allVehicles();
}

export function findVehicle(id: string | null): Vehicle | null {
	return vehicleById(id);
}

/**
 * Hand-authored names for the vehicles Wikidata has no item for: two ships out
 * of novels, and the archetypes, which are a propulsion type rather than a
 * craft anyone named. Everything else is named from its QID, which is the
 * whole reason the catalogue carries one.
 */
const NAME_MESSAGES: Record<string, () => string> = {
	'hail-mary': m.spacecraft_name_hail_mary,
	hermes: m.spacecraft_name_hermes,
	'ion-tug': m.spacecraft_name_ion_tug,
	'solar-sail': m.spacecraft_name_solar_sail,
	'nuclear-thermal-stage': m.spacecraft_name_nuclear_thermal_stage
};

/**
 * Localized name, for vehicles that have no Wikidata item to get one from.
 * Null means "look the QID up" — the caller already has that path for bodies.
 */
export function localName(vehicle: Vehicle): string | null {
	const message = NAME_MESSAGES[vehicle.id];
	return message ? message() : null;
}
