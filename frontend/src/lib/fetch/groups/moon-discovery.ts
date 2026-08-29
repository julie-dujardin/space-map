/**
 * Per-system moon discovery timelines: host object id → year → moons found.
 * Drives the discovery chart on a planetary system page, the same tally the
 * Moons collection charts but split by the system it happened in.
 * Fetched once and cached (a few hundred short histograms).
 */

import { DATA_BASE } from '$lib/fetch/data-base';

/** Host id (`naif-5`, or an asteroid's `spkid-…`) → year → count. */
export type MoonDiscoveryFile = Record<string, Record<string, number>>;

let pending: Promise<MoonDiscoveryFile> | null = null;

export function fetchMoonDiscovery(): Promise<MoonDiscoveryFile> {
	if (pending) return pending;
	pending = (async () => {
		const res = await fetch(`${DATA_BASE}/v1/groups/__moon_discovery__.json.gz`);
		if (!res.ok) throw new Error(`Failed to fetch moon discovery: ${res.status}`);
		const ds = new DecompressionStream('gzip');
		return (await new Response(res.body!.pipeThrough(ds)).json()) as MoonDiscoveryFile;
	})();
	return pending;
}
