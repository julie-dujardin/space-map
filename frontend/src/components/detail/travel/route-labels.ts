/** Names for the trajectories on offer, in one place so the list and the
 *  trajectory read off it cannot drift apart. */

import * as m from '$lib/paraglide/messages.js';
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
			return m.travel_profile_custom();
		case 'constant-thrust':
			return m.travel_profile_constant_thrust();
		case 'low-thrust':
			return m.travel_profile_low_thrust();
		case 'gravity-assist':
			return m.travel_profile_gravity_assist();
	}
}
