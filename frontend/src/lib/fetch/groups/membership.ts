/**
 * Earth-sat membership inverted index: one file per zone, `{slug: [id, ...]}`.
 * Static across snapshots — keyed by stable object id — so the file is
 * cache-forever and shared across every visit to a /g/<slug> page.
 */

import { versionedUrl } from '$lib/fetch/data-base';

export type EarthMembership = Record<string, string[]>;

let pending: Promise<EarthMembership> | null = null;

export function fetchEarthMembership(): Promise<EarthMembership> {
	if (pending) return pending;
	pending = (async () => {
		const res = await fetch(versionedUrl('/v1/membership/earth.json.gz', 'membership'));
		if (!res.ok) {
			if (res.status === 404) return {};
			throw new Error(`fetchEarthMembership: ${res.status} ${res.statusText}`);
		}
		const ds = new DecompressionStream('gzip');
		return (await new Response(res.body!.pipeThrough(ds)).json()) as EarthMembership;
	})();
	return pending;
}

/** Resolve a slug to the set of member object ids (empty set if unknown). */
export async function fetchEarthGroupMembers(slug: string): Promise<Set<string>> {
	const m = await fetchEarthMembership();
	return new Set(m[slug] ?? []);
}
