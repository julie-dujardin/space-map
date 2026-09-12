/**
 * Earth-sat membership inverted index: one file per zone, `{slug: [id, ...]}`.
 * Static across snapshots — keyed by stable object id — so the file is
 * cache-forever and shared across every visit to a /g/<slug> page.
 */

import { versionedUrl } from '$lib/fetch/data-base';
import { memoizedGzJson } from '$lib/fetch/gz';
import { fetchMetadata } from '$lib/fetch/metadata';

export type EarthMembership = Record<string, string[]>;

export const fetchEarthMembership = memoizedGzJson<EarthMembership>(
	async () => {
		// The version token comes from metadata; a group page can ask before
		// any other fetch has awaited it.
		await fetchMetadata();
		return versionedUrl('/v1/membership/earth.json.gz', 'membership');
	},
	{
		// No file ⇒ no members, not an error: the export may predate the index.
		onMissing: () => ({}),
		error: (res) => `fetchEarthMembership: ${res.status} ${res.statusText}`
	}
);

/** Resolve a slug to the set of member object ids (empty set if unknown). */
export async function fetchEarthGroupMembers(slug: string): Promise<Set<string>> {
	const m = await fetchEarthMembership();
	return new Set(m[slug] ?? []);
}
