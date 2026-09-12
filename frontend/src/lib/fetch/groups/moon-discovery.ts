/**
 * Per-system moon discovery timelines: host object id → year → moons found.
 * Drives the discovery chart on a planetary system page, the same tally the
 * Moons collection charts but split by the system it happened in.
 * Fetched once and cached (a few hundred short histograms).
 */

import { dataBase } from '$lib/fetch/data-base';
import { memoizedGzJson } from '$lib/fetch/gz';

/** Host id (`naif-5`, or an asteroid's `spkid-…`) → year → count. */
export type MoonDiscoveryFile = Record<string, Record<string, number>>;

export const fetchMoonDiscovery = memoizedGzJson<MoonDiscoveryFile>(
	() => `${dataBase()}/v1/groups/__moon_discovery__.json.gz`,
	{ error: (res) => `Failed to fetch moon discovery: ${res.status}` }
);
