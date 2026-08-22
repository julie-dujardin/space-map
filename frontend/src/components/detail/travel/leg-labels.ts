/** Names for the steps of a route, in one place so the ladder, the step list and
 *  the timeline cannot drift apart. */

import * as m from '$lib/paraglide/messages.js';
import type { TimelineKind } from '$lib/travel/timeline';

export function legLabel(kind: TimelineKind): string {
	switch (kind) {
		case 'start-orbit':
			return m.travel_leg_start_orbit();
		case 'final-orbit':
			return m.travel_leg_final_orbit();
		case 'ascent':
			return m.travel_leg_ascent();
		case 'injection':
			return m.travel_leg_injection();
		case 'cruise':
			return m.travel_leg_cruise();
		case 'boost':
			return m.travel_leg_boost();
		case 'brake':
			return m.travel_leg_brake();
		case 'powered-cruise':
			return m.travel_leg_powered_cruise();
		case 'spiral-out':
			return m.travel_leg_spiral_out();
		case 'spiral-in':
			return m.travel_leg_spiral_in();
		case 'assist':
			return m.travel_leg_assist();
		case 'capture':
			return m.travel_leg_capture();
		case 'rendezvous':
			return m.travel_leg_rendezvous();
		case 'aero-pass':
			return m.travel_leg_aero_pass();
		case 'aerobrake':
			return m.travel_leg_aerobrake();
		case 'raise':
			return m.travel_leg_raise();
		case 'descent':
			return m.travel_leg_descent();
	}
}
