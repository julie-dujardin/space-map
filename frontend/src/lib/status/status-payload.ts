/**
 * Shape of `/v1/status.json` plus the rows /status renders from it.
 * Mirror of `data/src/space_map_data/export/status.py`.
 */

import * as m from '$lib/paraglide/messages.js';

/** One download provider's freshness record. Dates are absent until the
 *  provider has run once, so the page can say a source never has. */
export interface StatusSource {
	id: string;
	label: string;
	homepage: string;
	category: string;
	/** Built from data already on disk rather than fetched; its date tracks the
	 *  pipeline step, not the upstream. */
	derived?: boolean;
	/** Age past which the scheduler should have refreshed the row: the
	 *  provider's own window plus the wait for the next scheduled pass. Absent
	 *  where a complete download is trusted for good. */
	due_after_days?: number;
	downloaded_at?: string;
	/** Last verified, where a provider tells the two apart (only SBDB does). */
	checked_at?: string;
	record_count?: number;
}

export interface Status {
	generated_at: string;
	categories: string[];
	sources: StatusSource[];
}

/** Section labels, keyed by the category ids the export ships. */
const CATEGORY_LABELS: Record<string, () => string> = {
	orbits: m.status_section_orbits,
	ephemerides: m.status_section_ephemerides,
	reference: m.status_section_reference,
	imagery: m.status_section_imagery,
	models: m.status_section_models,
	science: m.status_section_science
};

export function categoryLabel(id: string): string {
	return CATEGORY_LABELS[id]?.() ?? id;
}

/** What a row's age means, and whether it is worth acting on. */
export type Freshness = 'current' | 'due' | 'never';

export function freshness(source: StatusSource, now: number): Freshness {
	if (!source.downloaded_at) return 'never';
	if (source.due_after_days === undefined) return 'current';
	const checked = source.checked_at ?? source.downloaded_at;
	const ageDays = (now - Date.parse(checked)) / 86_400_000;
	return ageDays > source.due_after_days ? 'due' : 'current';
}

export interface StatusSection {
	id: string;
	label: string;
	sources: StatusSource[];
}

/** The payload's own category order, carrying only the sections that have rows. */
export function sections(status: Status): StatusSection[] {
	const out: StatusSection[] = [];
	for (const id of status.categories) {
		const sources = status.sources.filter((s) => s.category === id);
		if (sources.length > 0) out.push({ id, label: categoryLabel(id), sources });
	}
	// A category the frontend doesn't know about still gets a section rather
	// than dropping its rows off the page.
	const known = new Set(status.categories);
	const rest = status.sources.filter((s) => !known.has(s.category));
	for (const source of rest) {
		const section = out.find((s) => s.id === source.category);
		if (section) section.sources.push(source);
		else
			out.push({ id: source.category, label: categoryLabel(source.category), sources: [source] });
	}
	return out;
}

export interface StatusTally {
	total: number;
	current: number;
	due: number;
	never: number;
}

export function tally(status: Status, now: number): StatusTally {
	const counts = { total: status.sources.length, current: 0, due: 0, never: 0 };
	for (const source of status.sources) counts[freshness(source, now)] += 1;
	return counts;
}
