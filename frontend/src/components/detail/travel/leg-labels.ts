/** Names for the legs of a route, in one place so the ladder and the step list
 *  cannot drift apart. */

import * as m from '$lib/paraglide/messages.js';
import type { LegKind } from '$lib/math/travel';

export function legLabel(kind: LegKind): string {
	switch (kind) {
		case 'ascent':
			return m.travel_leg_ascent();
		case 'injection':
			return m.travel_leg_injection();
		case 'cruise':
			return m.travel_leg_cruise();
		case 'capture':
			return m.travel_leg_capture();
		case 'descent':
			return m.travel_leg_descent();
	}
}
