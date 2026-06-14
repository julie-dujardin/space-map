/** Thin Meilisearch wrapper for the search bar.
 *  Returns an empty hit list when the env isn't configured, so the UI can
 *  render a disabled state without special-casing the absence. */

import { Meilisearch } from 'meilisearch';
import { PUBLIC_MEILI_URL, PUBLIC_MEILI_SEARCH_KEY } from '$env/static/public';
import { pickedThumbnailUrl, type PickedThumbnail } from '$lib/fetch/objects/images';

/** Pre-resolved thumbnail descriptor written by the search indexer.
 *  Already narrowed to a single emitted variant — the frontend doesn't pick
 *  a size here, the dropdown always wants the smallest available. */
export type SearchThumbnail = PickedThumbnail;

export interface FeatureHit {
	kind: 'feature';
	id: string;
	feature_id: number;
	body_id: string;
	name: string;
	feature_type: string;
	center_lat: number;
	center_lon: number;
	diameter_km?: number;
	name_en?: string;
	name_fr?: string;
	name_ja?: string;
	name_zh?: string;
	name_ar?: string;
	name_ru?: string;
	description_en?: string;
	description_fr?: string;
	description_ja?: string;
	description_zh?: string;
	description_ar?: string;
	description_ru?: string;
	thumbnail?: SearchThumbnail;
}

export interface ObjectHit {
	kind: 'object';
	id: string;
	name: string;
	type: string;
	parent_id?: string;
	priority?: number;
	designations?: string[];
	ops_status?: string;
	/** Group slugs this object belongs to (small-body class/flags + earth-sat
	 *  collections) — the filter key behind a group's "show all members". */
	groups?: string[];
	/** Wikidata sitelink count; prominence rank for member listings. */
	sitelinks_count?: number;
	diameter_km?: number;
	/** Absolute magnitude (SBDB H, else Wikidata) — brightness tiebreak. */
	magnitude?: number;
	/** Sortable YYYYMMDD int: discovery/launch/inception. */
	inception?: number;
	name_en?: string;
	name_fr?: string;
	name_ja?: string;
	name_zh?: string;
	name_ar?: string;
	name_ru?: string;
	description_en?: string;
	description_fr?: string;
	description_ja?: string;
	description_zh?: string;
	description_ar?: string;
	description_ru?: string;
	thumbnail?: SearchThumbnail;
}

/** Constellation / operator / asteroid-class collection. The Meili primary
 *  key is ``slug``; we mirror it into ``id`` so the rest of the search UI
 *  can treat all hit kinds uniformly. */
export interface GroupHit {
	kind: 'group';
	id: string; // = slug
	slug: string;
	name: string;
	type: string;
	applies_to: string;
	member_count: number;
	name_en?: string;
	name_fr?: string;
	name_ja?: string;
	name_zh?: string;
	name_ar?: string;
	name_ru?: string;
	description_en?: string;
	description_fr?: string;
	description_ja?: string;
	description_zh?: string;
	description_ar?: string;
	description_ru?: string;
	thumbnail?: SearchThumbnail;
}

export type SearchHit = FeatureHit | ObjectHit | GroupHit;

let client: Meilisearch | null = null;
function getClient(): Meilisearch | null {
	if (!PUBLIC_MEILI_URL || !PUBLIC_MEILI_SEARCH_KEY) return null;
	if (!client) {
		client = new Meilisearch({ host: PUBLIC_MEILI_URL, apiKey: PUBLIC_MEILI_SEARCH_KEY });
	}
	return client;
}

export function isSearchEnabled(): boolean {
	return getClient() !== null;
}

/** Unified index name. Objects, surface features and group/collection pages
 *  all live in one index, discriminated by `kind`, so a single query ranks
 *  them together. */
const INDEX = 'catalog';

type RawHit = Record<string, unknown>;

/** Flatten a stored catalog doc into the kind-specific hit the UI consumes:
 *  shared fields stay at the root, per-kind fields lift out of the nested
 *  `object`/`feature`/`group` key, and `id` becomes the natural identifier the
 *  frontend routes on (the doc's root `id` is the URL-form Meili primary key). */
function toObjectHit(d: RawHit): ObjectHit {
	const o = (d.object ?? {}) as RawHit;
	return { ...d, ...o, kind: 'object', id: (o.id as string) ?? String(d.id) } as ObjectHit;
}

function toFeatureHit(d: RawHit): FeatureHit {
	const f = (d.feature ?? {}) as RawHit;
	return {
		...d,
		kind: 'feature',
		feature_id: f.feature_id as number,
		body_id: f.body_id as string,
		feature_type: f.type as string,
		center_lat: f.center_lat as number,
		center_lon: f.center_lon as number
	} as FeatureHit;
}

function toGroupHit(d: RawHit): GroupHit {
	const g = (d.group ?? {}) as RawHit;
	return {
		...d,
		kind: 'group',
		id: g.slug as string,
		slug: g.slug as string,
		type: g.type as string,
		applies_to: g.applies_to as string,
		member_count: (g.member_count as number) ?? 0
	} as GroupHit;
}

function toHit(d: RawHit): SearchHit {
	if (d.kind === 'group') return toGroupHit(d);
	if (d.kind === 'feature') return toFeatureHit(d);
	return toObjectHit(d);
}

/** Full-text search across the unified catalog. Objects, surface features and
 *  group/collection pages are ranked together (relevance, then Wikidata
 *  prominence), so a prominent body outranks a niche group of the same name. */
export async function search(
	query: string,
	locale: string,
	limit: number = 8
): Promise<SearchHit[]> {
	const c = getClient();
	if (!c || !query.trim()) return [];
	const res = await c.index(INDEX).search(query, { limit, locales: [locale] });
	return (res.hits ?? []).map((h) => toHit(h as RawHit));
}

/** One page of a group's members (objects) from the catalog index. */
export interface GroupMemberPage {
	hits: ObjectHit[];
	/** Capped at the index's maxTotalHits (1000). */
	estimatedTotalHits: number;
}

// Notable-first: prominence → size → brightness → age. Docs missing a key
// sort last for it. prominence/size are shared root fields; magnitude/inception
// are object-only, so they live under the nested `object` key.
const MEMBER_SORT = [
	'sitelinks_count:desc',
	'diameter_km:desc',
	'object.magnitude:asc',
	'object.inception:asc'
];

async function searchMemberPage(
	filter: string,
	offset: number,
	limit: number,
	locale: string
): Promise<GroupMemberPage> {
	const c = getClient();
	if (!c) return { hits: [], estimatedTotalHits: 0 };
	const res = await c.index(INDEX).search('', {
		filter,
		sort: MEMBER_SORT,
		offset,
		limit,
		locales: [locale]
	});
	const hits = (res.hits ?? []).map((h) => toObjectHit(h as RawHit));
	return { hits, estimatedTotalHits: res.estimatedTotalHits ?? hits.length };
}

/** A paginated slice of a group's members (small-body class/flag or earth-sat
 *  collection), ranked notable-first. Empty when search is unconfigured or the
 *  slug tags no objects (e.g. categories / split-comet families). */
export function searchGroupMembers(
	slug: string,
	offset: number,
	limit: number,
	locale: string
): Promise<GroupMemberPage> {
	return searchMemberPage(`object.groups = "${slug}"`, offset, limit, locale);
}

/** A paginated slice of a body's moons, ranked notable-first. `parentId` is the
 *  host body's Object id (a planet/dwarf-planet; its barycenter's moons are
 *  re-parented to it in the index). The planet itself shares that parent_id, so
 *  the `type` clause keeps moons only. */
export function searchChildMembers(
	parentId: string,
	offset: number,
	limit: number,
	locale: string
): Promise<GroupMemberPage> {
	return searchMemberPage(
		`object.parent_id = "${parentId}" AND object.type = "moon"`,
		offset,
		limit,
		locale
	);
}

/** Display name for a hit in the active locale, falling back to canonical. */
export function localizedName(hit: SearchHit, locale: string): string {
	const field = `name_${locale}` as keyof SearchHit;
	const v = hit[field as keyof typeof hit];
	if (typeof v === 'string' && v) return v;
	return hit.name;
}

/** Localized Wikidata description for a hit, or undefined. Falls back to
 *  English when the active locale has no description. */
export function localizedDescription(hit: SearchHit, locale: string): string | undefined {
	const field = `description_${locale}` as keyof typeof hit;
	const v = hit[field];
	if (typeof v === 'string' && v) return v;
	const en = hit.description_en;
	if (typeof en === 'string' && en) return en;
	return undefined;
}

/** URL for the dropdown thumbnail, or undefined when the hit has no image. */
export function thumbnailUrl(hit: SearchHit): string | undefined {
	const t = hit.thumbnail;
	if (!t) return undefined;
	return pickedThumbnailUrl(t);
}
