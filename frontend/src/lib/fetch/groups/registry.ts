/**
 * Group registry loader: small JSON index of every known group, fetched once
 * on demand. Lets routing validate `/g/<slug>` URLs and powers listings
 * without paying for the per-group detail bundle.
 */

import { DATA_BASE } from '$lib/fetch/data-base';
import { fetchWithTimeout } from '$lib/fetch/fetch-timeout';
import * as m from '$lib/paraglide/messages.js';

export type GroupType =
	| 'constellation'
	| 'launch_vehicle'
	| 'organization'
	| 'launch_site'
	| 'bus'
	| 'country'
	| 'orbit_class'
	| 'small_body_flag'
	| 'earth_orbit_class'
	| 'category'
	| 'split_comet'
	| 'mission'
	| 'feature_type';

/** An organization's role tags, surfaced as badges on its /g/org-<slug> page. */
export type OrganizationRole = 'operator' | 'manufacturer';
export type GroupCategory = 'earth_sat' | 'small_body' | 'category' | 'probe' | 'surface_feature';

/** Mirrors ``CONSTELLATION_SLUG_PREFIX`` in
 *  ``data/constants/earth_sats/constellations.py``. */
export const CONSTELLATION_SLUG_PREFIX = 'const-';

/** Mirrors ``CLASS_SLUG_PREFIX`` in ``data/export/groups/registry.py``. */
export const CLASS_SLUG_PREFIX = 'class-';

/** Mirrors ``FAMILY_GROUP_SLUG_PREFIX`` in ``data/constants/comet_fragments.py``. */
export const COMET_FAMILY_SLUG_PREFIX = 'comet-family-';

/** Mirrors ``MISSION_SLUG_PREFIX`` in ``data/export/objects/missions.py``. */
export const MISSION_SLUG_PREFIX = 'mission-';

/** Mirrors ``SMALL_BODY_FLAG_SLUG_PREFIX`` in ``data/export/groups/registry.py``. */
export const SMALL_BODY_FLAG_SLUG_PREFIX = 'flag-';

/** Mirrors ``FEATURE_TYPE_SLUG_PREFIX`` in
 *  ``data/constants/nomenclature/feature_types.py``. */
export const FEATURE_TYPE_SLUG_PREFIX = 'ft-';

/** Mirrors ``CATEGORY_SLUG_PREFIX`` in ``data/constants/categories.py``. */
export const CATEGORY_SLUG_PREFIX = 'cat-';
export const CAT_SOLAR_SYSTEM = `${CATEGORY_SLUG_PREFIX}solar-system`;
export const CAT_PLANETS = `${CATEGORY_SLUG_PREFIX}planets`;
export const CAT_DWARF_PLANETS = `${CATEGORY_SLUG_PREFIX}dwarf-planets`;
export const CAT_MOONS = `${CATEGORY_SLUG_PREFIX}moons`;
export const CAT_ASTEROIDS = `${CATEGORY_SLUG_PREFIX}asteroids`;
export const CAT_COMETS = `${CATEGORY_SLUG_PREFIX}comets`;
export const CAT_SATELLITES = `${CATEGORY_SLUG_PREFIX}satellites`;
export const CAT_PROBES = `${CATEGORY_SLUG_PREFIX}probes`;
export const CAT_SURFACE_FEATURES = `${CATEGORY_SLUG_PREFIX}surface-features`;

/** Plural category headers, not the singular Wikidata label. */
const CATEGORY_NAME: Record<string, () => string> = {
	[CAT_SOLAR_SYSTEM]: m.category_name_solar_system,
	[CAT_PLANETS]: m.category_name_planets,
	[CAT_DWARF_PLANETS]: m.category_name_dwarf_planets,
	[CAT_MOONS]: m.category_name_moons,
	[CAT_ASTEROIDS]: m.category_name_asteroids,
	[CAT_COMETS]: m.category_name_comets,
	[CAT_SATELLITES]: m.category_name_satellites,
	[CAT_PROBES]: m.category_name_probes,
	[CAT_SURFACE_FEATURES]: m.category_name_surface_features
};

/** Localized display name for a `cat-` slug; the raw slug if unknown. */
export function categoryLabel(slug: string): string {
	return CATEGORY_NAME[slug]?.() ?? slug;
}

/** Slug suffix → flag bit mask. Mirrors `ELEMENTS_FLAG_*` in
 *  `$lib/fetch/position/elements/parse.ts`. */
export const SMALL_BODY_FLAG_MASK = {
	neo: 0x01,
	pha: 0x02
} as const satisfies Record<string, number>;

export type SmallBodyFlagName = keyof typeof SMALL_BODY_FLAG_MASK;

/** SBDB orbit-class names that are comets; every other class is an asteroid.
 *  Mirrors COMET_ORBIT_CLASSES in data/constants/categories.py. */
export const COMET_CLASS_NAMES: ReadonlySet<string> = new Set([
	'ETc',
	'JFc',
	'JFC',
	'CTc',
	'HTC',
	'PAR',
	'HYP',
	'COM'
]);

export type SmallBodyCategory = 'asteroid' | 'comet';

/** Bucket an SBDB orbit-class name into the asteroid or comet category. */
export function smallBodyCategory(className: string): SmallBodyCategory {
	return COMET_CLASS_NAMES.has(className) ? 'comet' : 'asteroid';
}

/** Active small-body group filter. `class` hides non-matching zones; `category`
 *  hides every zone outside the asteroid/comet bucket (the Asteroids/Comets
 *  category pages); `flag` keeps zones visible and masks per-point via the orbit
 *  worker's `requiredFlags`. `n` is the index's total so emphasis ramps without
 *  a refetch. */
export type SmallBodyFilter =
	| { kind: 'class'; className: string }
	| { kind: 'category'; category: SmallBodyCategory }
	| { kind: 'flag'; flag: SmallBodyFlagName; mask: number; n: number };

export function smallBodyFiltersEqual(
	a: SmallBodyFilter | null,
	b: SmallBodyFilter | null
): boolean {
	if (a === b) return true;
	if (a === null || b === null) return false;
	if (a.kind !== b.kind) return false;
	if (a.kind === 'class' && b.kind === 'class') return a.className === b.className;
	if (a.kind === 'category' && b.kind === 'category') return a.category === b.category;
	if (a.kind === 'flag' && b.kind === 'flag') return a.flag === b.flag;
	return false;
}

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
	/** Feature-type groups only: the 2-letter IAU descriptor code. */
	code?: string;
}

export type GroupIndex = Record<string, GroupIndexEntry>;

let pending: Promise<GroupIndex> | null = null;

/** IAU code ↔ ft- slug, resolved from the group index so the 57-entry table
 *  lives in one place (the export) rather than being mirrored here. */
export async function featureTypeCode(slug: string): Promise<string | undefined> {
	return (await fetchGroupIndex())[slug]?.code;
}

export async function featureTypeSlug(code: string): Promise<string | undefined> {
	const index = await fetchGroupIndex();
	for (const [slug, entry] of Object.entries(index)) {
		if (entry.code === code) return slug;
	}
	return undefined;
}

export function fetchGroupIndex(): Promise<GroupIndex> {
	if (pending) return pending;
	const p = fetchWithTimeout(`${DATA_BASE}/v1/groups/__index__.json`).then((r) => {
		if (!r.ok) throw new Error(`Failed to fetch group index: ${r.status}`);
		return r.json() as Promise<GroupIndex>;
	});
	pending = p;
	// Evict on rejection so a transient failure doesn't poison group routing.
	p.catch(() => {
		if (pending === p) pending = null;
	});
	return pending;
}
