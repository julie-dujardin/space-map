/** Display names for the craft catalogue. A switch rather than a dynamic key
 *  lookup so a renamed message is a compile error, not a blank label. */

import * as m from '$lib/paraglide/messages.js';
import type { CatalogueEntry } from '$lib/travel/vehicles';

export function vehicleName(vehicle: CatalogueEntry): string {
	switch (vehicle.nameKey) {
		case 'falcon_heavy':
			return m.vehicle_falcon_heavy();
		case 'sls_block_1b':
			return m.vehicle_sls_block_1b();
		case 'apollo_csm':
			return m.vehicle_apollo_csm();
		case 'starship':
			return m.vehicle_starship();
		case 'epstein':
			return m.vehicle_epstein();
		default:
			return vehicle.id;
	}
}
