/**
 * Group registry loader: small JSON index of every known group, fetched once
 * on demand. Lets routing validate `/g/<slug>` URLs and powers listings
 * without paying for the per-group detail bundle.
 */

import { DATA_BASE } from '$lib/fetch/data-base';

export type GroupType = 'constellation' | 'operator' | 'launch_site' | 'manufacturer' | 'country';
export type GroupCategory = 'earth_sat';

/** Mirrors ``SatelliteCategory`` in ``data/constants/earth_sats/constellations.py``. */
export type SatelliteCategory =
	| 'disaster-sar'
	| 'weather'
	| 'observation'
	| 'communications'
	| 'navigation'
	| 'science'
	| 'military'
	| 'debris'
	| 'station'
	| 'manned_capsule'
	| 'unmanned_cargo'
	| 'space_tug'
	| 'rocket'
	| 'upper_stage'
	| 'miscellaneous';

export interface GroupIndexEntry {
	type: GroupType;
	applies_to: GroupCategory;
	/** Member count baked at export time. */
	n: number;
}

export type GroupIndex = Record<string, GroupIndexEntry>;

let pending: Promise<GroupIndex> | null = null;

export function fetchGroupIndex(): Promise<GroupIndex> {
	if (pending) return pending;
	pending = fetch(`${DATA_BASE}/v1/groups/__index__.json`).then((r) => {
		if (!r.ok) throw new Error(`Failed to fetch group index: ${r.status}`);
		return r.json() as Promise<GroupIndex>;
	});
	return pending;
}
