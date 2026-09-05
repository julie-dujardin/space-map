/**
 * The curated record read as a destination list: events grouped by the body
 * they were directed at, most recent stop first. The Targets tab and the
 * overview strip both read it, so the two cannot disagree on what counts.
 *
 * An orbit is told as a stay: the insertion opens it and the next departure,
 * landing or (re)entry at the same body closes it, so "Orbit 2004 – 2017"
 * rather than two dated moments. Repeats of one activity (a second gravity
 * assist) list their years instead of a range that would read as one long
 * event.
 */

import * as m from '$lib/paraglide/messages.js';
import type { EntityRef, ProbeEvent } from '$lib/fetch/objects/object-data';
import { eventDay, eventLabel, flybyPurposeLabel, formatIsoDay } from './event-labels';

export interface ActivityLine {
	label: string;
	dates: string;
}

export interface TargetVisit {
	target: NonNullable<ProbeEvent['target']>;
	/** The focusable object id behind the target, when it has one. */
	objectId?: string;
	/** One line per activity, in the order they first happened. */
	activities: ActivityLine[];
	/** When the craft was last there — the list's sort key. */
	lastJd: number;
}

/** The focusable object id behind an event target, when it has one. */
export function targetObjectId(target: EntityRef): string | undefined {
	return target.primary_type && target.primary_id
		? `${target.primary_type}-${target.primary_id}`
		: undefined;
}

const ORBIT_CLOSERS = new Set(['orbit_departure', 'reentry', 'atmospheric_entry', 'landing']);

function activityLines(events: ProbeEvent[]): ActivityLine[] {
	type Entry = { label: string; dates?: string; events: ProbeEvent[] };
	const entries: Entry[] = [];
	const byLabel = new Map<string, Entry>();
	const skip = new Set<ProbeEvent>();
	for (let i = 0; i < events.length; i++) {
		const event = events[i];
		if (skip.has(event)) continue;
		if (event.type === 'orbit_insertion' && !event.failed) {
			const closer = events.slice(i + 1).find((e) => ORBIT_CLOSERS.has(e.type));
			// The departure is the stay's end and says nothing more; a closing
			// landing or entry is its own further event and keeps its line.
			if (closer?.type === 'orbit_departure') skip.add(closer);
			entries.push({
				label: m.probe_event_orbit(),
				dates: closer
					? `${formatIsoDay(event.date)} – ${formatIsoDay(closer.date)}`
					: formatIsoDay(event.date),
				events: []
			});
			continue;
		}
		const purpose = flybyPurposeLabel(event);
		const label = purpose ? `${eventLabel(event)} (${purpose})` : eventLabel(event);
		const open = byLabel.get(label);
		if (open) open.events.push(event);
		else {
			const entry = { label, events: [event] };
			byLabel.set(label, entry);
			entries.push(entry);
		}
	}
	return entries.map((e) => ({
		label: e.label,
		dates:
			e.dates ??
			(e.events.length === 1
				? eventDay(e.events[0])
				: [...new Set(e.events.map((ev) => ev.date.slice(0, 4)))].join(', '))
	}));
}

const EARTH_ID = 'naif-399';

/** Whether an event names somewhere the craft was sent. A craft it carried or
 *  rode is not a destination, and neither is the Earth it left or came back
 *  to; Earth counts only when the craft flew past or orbited it on purpose. */
function isDestination(event: ProbeEvent): boolean {
	const target = event.target!;
	if (target.primary_type === 'probe') return false;
	if (targetObjectId(target) === EARTH_ID) {
		return event.type === 'flyby' || event.type === 'orbit_insertion';
	}
	return true;
}

export function targetVisits(items: readonly ProbeEvent[]): TargetVisit[] {
	const byTarget = new Map<
		string,
		{ target: NonNullable<ProbeEvent['target']>; events: ProbeEvent[] }
	>();
	for (const event of items) {
		if (!event.target || !isDestination(event)) continue;
		const key = targetObjectId(event.target) ?? event.target.name;
		let group = byTarget.get(key);
		if (!group) byTarget.set(key, (group = { target: event.target, events: [] }));
		group.events.push(event);
	}
	const visits = [...byTarget.values()].map(({ target, events }) => {
		const last = events[events.length - 1];
		return {
			target,
			objectId: targetObjectId(target),
			activities: activityLines(events),
			lastJd: last.end_jd ?? last.jd
		};
	});
	return visits.sort((a, b) => b.lastJd - a.lastJd);
}
