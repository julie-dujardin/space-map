/** Names for the trajectories on offer, in one place so the list and the
 *  trajectory read off it cannot drift apart. */

import * as m from '$lib/paraglide/messages.js';
import type { RouteFamily } from '$lib/travel/route-families';
import type { RouteOption } from '$lib/travel/trip';

export function routeLabel(profile: RouteOption): string {
	switch (profile) {
		case 'fast':
			return m.travel_profile_fast();
		case 'balanced':
			return m.travel_profile_balanced();
		case 'efficient':
			return m.travel_profile_efficient();
		case 'custom':
		case 'constant-thrust-custom':
			return m.travel_profile_custom();
		// Rows are named for how much of the crossing the drive is on for; only
		// the first one holds it throughout.
		case 'constant-thrust':
			return m.travel_profile_constant_thrust();
		case 'constant-thrust-balanced':
			return m.travel_profile_balanced();
		case 'constant-thrust-efficient':
			return m.travel_profile_efficient();
		case 'low-thrust':
			return m.travel_profile_low_thrust();
		case 'gravity-assist':
			return m.travel_profile_gravity_assist();
	}
}

/** A family's tab. Families with one trajectory reuse its name; the held-arc
 *  family is named for the curve, since its rows are points on it. */
export function familyLabel(family: RouteFamily): string {
	switch (family) {
		case 'transfer':
			return m.travel_family_transfer();
		case 'gravity-assist':
			return m.travel_profile_gravity_assist();
		case 'constant-thrust':
			return m.travel_family_brachistochrone();
		case 'low-thrust':
			return m.travel_profile_low_thrust();
	}
}
