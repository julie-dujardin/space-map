/**
 * When each spacecraft was last talked to, from `{liveUrl}/v1/activity.json`.
 * The poller rewrites the file every few minutes, so it is fetched on demand
 * and kept only briefly; an object absent from it has not been seen since its
 * network's feed started, which is not the same as silence.
 */

import { host } from '$lib/host';
import { fetchWithTimeout } from './fetch-timeout';

export type ActivityNetwork = 'dsn' | 'dsn-bot' | 'estrack';

/** How much of the timestamp the network stands behind: ESTRACK publishes
 *  its schedule by month, so `last_contact` is then a bare `YYYY-MM`. */
export type ActivityPrecision = 'second' | 'minute' | 'month';

export interface ActivitySource {
	network: string;
	measures: string;
	precision: ActivityPrecision;
	via: string;
	credit?: string;
	/** When this feed started; nothing before it was seen. */
	since: string | null;
}

export interface ActivityEntry {
	/** The most recent sighting across networks, ISO 8601 at `precision`. */
	last_contact: string;
	precision: ActivityPrecision;
	network: ActivityNetwork;
	/** Every network's own last sighting, since they measure different things. */
	seen: Partial<Record<ActivityNetwork, { code: string; last_contact: string }>>;
}

export interface ActivityFile {
	generated_at: string;
	sources: Record<ActivityNetwork, ActivitySource>;
	objects: Record<string, ActivityEntry>;
}

/** Past this the edge has a newer copy; a reader who keeps a panel open for
 *  an hour still gets the pass that happened meanwhile. */
const MAX_AGE_MS = 5 * 60_000;

let cached: { at: number; promise: Promise<ActivityFile | null> } | null = null;

/** The feed, refetched once it is a few minutes old. Null when unreachable:
 *  the panel then shows the status without a contact time. */
export function fetchActivity(): Promise<ActivityFile | null> {
	const now = Date.now();
	if (cached && now - cached.at < MAX_AGE_MS) return cached.promise;
	const promise = (async () => {
		try {
			const r = await fetchWithTimeout(`${host().liveUrl}/v1/activity.json`);
			if (!r.ok) {
				console.warn(`activity: fetch failed (${r.status})`);
				return null;
			}
			return (await r.json()) as ActivityFile;
		} catch (e) {
			console.warn('activity: fetch failed', e);
			return null;
		}
	})();
	cached = { at: now, promise };
	return promise;
}
