import { getLocale } from '$lib/paraglide/runtime.js';

/**
 * Format a Wikidata/Wikipedia ISO 8601 date string as a localized date.
 * - Strips leading '+' (e.g. "+1801-01-01T00:00:00Z")
 * - When time is midnight, returns a localized date string (e.g. "January 1, 1801")
 * - When time is non-zero, returns "<localized date> <localized time>"
 */
export function formatWikidataDate(raw: string): string {
	const s = raw.startsWith('+') ? raw.slice(1) : raw;
	const tIdx = s.indexOf('T');
	if (tIdx === -1) return s;
	const date = s.slice(0, tIdx);
	const time = s.slice(tIdx + 1);
	const d = new Date(date + 'T' + time);
	const localDate = d.toLocaleDateString(getLocale(), {
		timeZone: 'UTC',
		year: 'numeric',
		month: 'long',
		day: 'numeric'
	});
	if (time === '00:00:00Z') return localDate;
	const localTime = d.toLocaleTimeString(getLocale(), { timeZone: 'UTC' });
	return `${localDate} ${localTime}`;
}
