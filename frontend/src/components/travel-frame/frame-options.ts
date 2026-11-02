/**
 * The two frames a trip's ends can be drawn in, as the map chrome offers them.
 *
 * Kept apart from the control so the two frames are described in one place,
 * whatever shape the control ends up being.
 */

import SunIcon from '@lucide/svelte/icons/sun';
import GlobeIcon from '@lucide/svelte/icons/globe';
import * as m from '$lib/paraglide/messages.js';
import type { TrajectoryFrame } from '$lib/math/travel';
import type { PillOption } from '../map-pill/pill-option';

/** Interplanetary first: it is the frame the crossing itself is in, and the one
 *  the map is in everywhere outside a sphere of influence. `aboutStar` says that a
 *  star other than the Sun is the centre of that frame. */
export function frameOptions(aboutStar = false): PillOption<TrajectoryFrame>[] {
	return [
		{
			value: 'interplanetary',
			label: m.travel_frame_interplanetary(),
			description: aboutStar ? m.travel_frame_star_desc() : m.travel_frame_interplanetary_desc(),
			Icon: SunIcon
		},
		{
			value: 'planetary',
			label: m.travel_frame_planetary(),
			description: m.travel_frame_planetary_desc(),
			Icon: GlobeIcon
		}
	];
}
