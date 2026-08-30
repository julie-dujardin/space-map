/**
 * What to call a curated mission event.
 *
 * The record states the type; the words for it are the interface's, and both
 * the drawer list and the strip along the map read them from here so the same
 * event cannot be two things in one session.
 */

import * as m from '$lib/paraglide/messages.js';
import { formatIsoDate } from '$lib/format/date';
import type { ProbeEvent } from '$lib/fetch/objects/object-data';

const TYPE_LABELS: Record<string, () => string> = {
	launch: m.probe_event_launch,
	stage_separation: m.probe_event_stage_separation,
	flyby: m.probe_event_flyby,
	orbit_insertion: m.probe_event_orbit_insertion,
	orbit_departure: m.probe_event_orbit_departure,
	atmospheric_entry: m.probe_event_atmospheric_entry,
	landing: m.probe_event_landing,
	reentry: m.probe_event_reentry,
	sample_collection: m.probe_event_sample_collection,
	sample_return: m.probe_event_sample_return,
	observation: m.probe_event_observation,
	perihelion: m.probe_event_perihelion,
	contact_loss: m.probe_event_contact_loss,
	hibernation: m.probe_event_hibernation,
	anomaly: m.probe_event_anomaly,
	mission_end: m.probe_event_mission_end,
	milestone: m.probe_event_milestone
};

/** An arrival that destroyed the craft is an impact, whether it was meant or
 *  not — calling it a landing reads as a success it wasn't. */
export function eventLabel(event: ProbeEvent): string {
	if (event.type === 'landing' && event.outcome === 'destroyed_at_landing') {
		return m.probe_event_landing_impact();
	}
	return TYPE_LABELS[event.type]?.() ?? event.type;
}

/** Why the craft flew past, where the sources say. */
export function flybyPurposeLabel(event: ProbeEvent): string | null {
	if (event.purpose === 'gravity_assist') return m.probe_flyby_purpose_gravity_assist();
	if (event.purpose === 'science') return m.probe_flyby_purpose_science();
	return null;
}

/** An ISO date at day precision, never finer — a time of day is more width
 *  than either timeline is worth. A bare year stays a year. */
export function formatIsoDay(iso: string): string {
	return formatIsoDate(iso.split('T')[0]);
}

/** The event's date at the record's own precision, capped at the calendar
 *  day; a span reads as its two ends. */
export function eventDay(event: ProbeEvent): string {
	return event.end_date
		? `${formatIsoDay(event.date)} – ${formatIsoDay(event.end_date)}`
		: formatIsoDay(event.date);
}

/** Where it happened, in the few words a card has room for: the body it was
 *  directed at, and the place on it when one is named. */
export function eventPlace(event: ProbeEvent): string {
	const parts = [event.target?.name, event.site?.name].filter(Boolean) as string[];
	return parts.join(' · ');
}
