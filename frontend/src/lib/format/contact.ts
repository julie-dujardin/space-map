import * as m from '$lib/paraglide/messages.js';
import type { ActivityEntry, ActivityNetwork, HistoryEntry } from '$lib/fetch/activity';
import { dateToJD, unixMsToJD } from '$lib/time/jd';
import { formatIsoDate, formatJulianDateRelative, formatJulianDateTime } from './date';

// The bot reads the same antennas as the DSN feed, so it carries its name.
const NETWORK_NAME: Record<ActivityNetwork, () => string> = {
	dsn: m.network_dsn,
	'dsn-bot': m.network_dsn,
	estrack: m.network_estrack
};

// Short months: the card holds one line and "September 6, 2025" is not one.
const DAY: Intl.DateTimeFormatOptions = { year: 'numeric', month: 'short', day: 'numeric' };
const TIME: Intl.DateTimeFormatOptions = { ...DAY, hour: '2-digit', minute: '2-digit' };

/** Past this "2 years ago" says less than the date does. */
const RELATIVE_WINDOW_DAYS = 30;

// A day, month or year is a span of calendar, not an instant to count from.
const CALENDAR = new Set(['day', 'month', 'year']);

/** The contact as a glance: how long ago while it is recent, the day once it
 *  is not, or the day, month or year when that is all the source says. */
export function formatLastContact(entry: ActivityEntry | HistoryEntry, nowMs = Date.now()): string {
	if (CALENDAR.has(entry.precision)) return formatIsoDate(entry.last_contact, 'short');
	const jd = dateToJD(new Date(entry.last_contact));
	const nowJd = unixMsToJD(nowMs);
	if (nowJd - jd > RELATIVE_WINDOW_DAYS) return formatJulianDateTime(jd, DAY);
	return formatJulianDateRelative(jd, nowJd);
}

/** The contact in full: the moment, and the network that had it when the
 *  live feed did. */
export function describeLastContact(entry: ActivityEntry | HistoryEntry): string {
	if (!('network' in entry))
		return m.tooltip_last_contact_record({ date: formatIsoDate(entry.last_contact) });
	const network = NETWORK_NAME[entry.network]();
	if (entry.precision === 'month')
		return m.tooltip_last_contact_month({ network, month: formatIsoDate(entry.last_contact) });
	return m.tooltip_last_contact({
		network,
		time: formatJulianDateTime(dateToJD(new Date(entry.last_contact)), TIME)
	});
}
