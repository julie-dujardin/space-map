/**
 * What a craft is called in the picker.
 *
 * The catalogue is data now, so names come with it: `name` is the English label
 * from the constants, and `localName` covers the handful of fictional ships
 * Wikidata has no item for. Everything else carries a `qid`, which is the hook
 * for localized labels once there is a bundle to read them from — until then
 * the English name is what shows.
 */

import type { Vehicle } from '$lib/math/travel';
import { localName } from '$lib/travel/vehicles';

export function vehicleName(vehicle: Vehicle): string {
	return localName(vehicle) ?? vehicle.name ?? vehicle.id;
}
