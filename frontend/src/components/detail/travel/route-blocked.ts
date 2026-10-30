/**
 * Why the chosen craft cannot fly a trajectory. Gives the two lines a row shows
 * in place of its figures. It sits beside the list because the cruise box shows
 * a row as well. Also gives the lines the panel shows when the craft has no
 * route between two stars.
 */

import * as m from '$lib/paraglide/messages.js';
import { formatNumber, formatQuantity } from '$lib/format/quantities';
import { formatDvBrief } from '$lib/travel/format';
import { jdToDate, LAST_DATE_JD } from '$lib/time/jd';
import type { InterstellarRefusal, Route } from '$lib/math/travel';
import type { TravelPanelState } from '$lib/travel/panel.svelte';
import { departureNote } from './vehicle-labels';

export interface Blocked {
	header: string;
	detail: string;
}

export function blockedText(state: TravelPanelState, route: Route): Blocked | null {
	const result = state.feasibility(route);
	if (!result || result.status === 'ok') return null;
	const out = (detail: string) => ({ header: m.travel_out_of_reach(), detail });
	// "Out of reach" is a claim about the vehicle. These cases refuse to judge it
	// at all, and say so.
	const unjudged = (detail: string) => ({ header: m.travel_unjudged(), detail });
	if (result.status === 'over-c3') {
		return out(m.travel_needs_c3({ value: formatNumber(route.c3Km2S2) }));
	}
	if (result.status === 'insufficient-dv') {
		return out(m.travel_needs_dv({ value: formatDvBrief(route.inSpaceDvKms) }));
	}
	// About the craft, not this route. The two disagree about where it starts.
	if (result.status === 'wrong-departure' && state.vehicle) {
		return out(departureNote(state.vehicle));
	}
	// Also about the craft. It has no published aeroshell to fly behind.
	if (result.status === 'no-aeroshell') {
		return out(m.travel_no_aeroshell());
	}
	// A launcher lifts a payload to one energy, so the same cargo clears one
	// trajectory and fails the next.
	if (result.status === 'over-payload' && result.payloadKg !== undefined) {
		return out(
			m.travel_lifts({
				value: formatQuantity({ value: result.payloadKg, unit: 'kilogram' }, true)
			})
		);
	}
	if (result.status === 'unknown') {
		return unjudged(m.travel_no_published_figure());
	}
	if (result.status === 'beyond-published') {
		const end = state.vehicle?.c3Curve?.points.at(-1)?.[0];
		return unjudged(
			end === undefined
				? m.travel_no_published_figure()
				: m.travel_past_published({ value: formatNumber(end) })
		);
	}
	// The last case. The drive cannot burn impulsively, and this trajectory needs
	// two such burns. That drive has a row of its own above.
	return unjudged(m.travel_thrust_too_low());
}

const REFUSAL_TEXT: Record<InterstellarRefusal, () => string> = {
	'no-craft': m.travel_refusal_no_craft,
	'no-drive': m.travel_refusal_no_drive,
	'low-thrust': m.travel_refusal_low_thrust,
	'cannot-escape': m.travel_refusal_cannot_escape,
	'cannot-stop': m.travel_refusal_cannot_stop
};

/** Why the chosen craft has no route between two stars. */
export function refusalText(refusal: InterstellarRefusal): string {
	return REFUSAL_TEXT[refusal]();
}

/** The year of the last date that a `Date` holds. */
const LAST_YEAR = jdToDate(LAST_DATE_JD).getUTCFullYear();

/** Why no "arrive by" date admits the crossing: the fastest one ends after the
 *  last date that can be shown. */
export function pastCalendarText(): string {
	return m.travel_no_routes_past_calendar({ year: formatNumber(LAST_YEAR) });
}
