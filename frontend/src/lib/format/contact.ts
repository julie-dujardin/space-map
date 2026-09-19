import * as m from '$lib/paraglide/messages.js';
import { getLocale } from '$lib/paraglide/runtime.js';
import type { ActivityEntry, ActivityNetwork } from '$lib/fetch/activity';
import { dateToJD, unixMsToJD } from '$lib/time/jd';
import { formatJulianDateRelative, formatJulianDateTime } from './date';

// The bot reads the same antennas as the DSN feed, so it carries its name.
const NETWORK_NAME: Record<ActivityNetwork, () => string> = {
	dsn: m.network_dsn,
	'dsn-bot': m.network_dsn,
	estrack: m.network_estrack
};

// Short months: the card holds one line and "September 6, 2025" is not one.
const DAY: Intl.DateTimeFormatOptions = { year: 'numeric', month: 'short', day: 'numeric' };
const TIME: Intl.DateTimeFormatOptions = { ...DAY, hour: '2-digit', minute: '2-digit' };

function formatMonth(raw: string, month: 'short' | 'long'): string {
	const [year, mon] = raw.split('-').map(Number);
	return new Intl.DateTimeFormat(getLocale(), { year: 'numeric', month, timeZone: 'UTC' }).format(
		new Date(Date.UTC(year, mon - 1, 1))
	);
}

/** Past this "2 years ago" says less than the date does. */
const RELATIVE_WINDOW_DAYS = 30;

/** The contact as a glance: how long ago while it is recent, the day once it
 *  is not, or the month when that is all the network says. */
export function formatLastContact(entry: ActivityEntry, nowMs = Date.now()): string {
	if (entry.precision === 'month') return formatMonth(entry.last_contact, 'short');
	const jd = dateToJD(new Date(entry.last_contact));
	const nowJd = unixMsToJD(nowMs);
	if (nowJd - jd > RELATIVE_WINDOW_DAYS) return formatJulianDateTime(jd, DAY);
	return formatJulianDateRelative(jd, nowJd);
}

/** The contact in full: the moment and the network that had it. */
export function describeLastContact(entry: ActivityEntry): string {
	const network = NETWORK_NAME[entry.network]();
	if (entry.precision === 'month')
		return m.tooltip_last_contact_month({
			network,
			month: formatMonth(entry.last_contact, 'long')
		});
	return m.tooltip_last_contact({
		network,
		time: formatJulianDateTime(dateToJD(new Date(entry.last_contact)), TIME)
	});
}
