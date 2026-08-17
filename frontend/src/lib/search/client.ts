/** Thin Meilisearch wrapper for the search bar.
 *  Returns an empty hit list when the env isn't configured, so the UI can
 *  render a disabled state without special-casing the absence. */

import type { Meilisearch } from 'meilisearch';
import { env } from '$env/dynamic/public';
import { pickedThumbnailUrl, type PickedThumbnail } from '$lib/fetch/objects/images';
import {
	CLASS_SLUG_PREFIX,
	FEATURE_TYPE_SLUG_PREFIX,
	featureTypeCode
} from '$lib/fetch/groups/registry';

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

/** Constellation / organization / asteroid-class collection. The Meili primary
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

/**
 * A launch pad. Indexed to be departed from rather than to be read about, so
 * the hit carries where it is and which collection page it belongs to, and
 * nothing else — there is no pad page to send a reader to.
 */
export interface PadHit {
	kind: 'pad';
	id: string;
	/** GCAT launch-point code, unique within its site. */
	code: string;
	/** The pad's own name, with the place it sits in trimmed off. */
	name: string;
	/** The `site-` collection holding it, and what that place is called. */
	site_slug: string;
	site_name: string;
	lat: number;
	lon: number;
	/** Distinct launches flown from it. Zero is common and real. */
	launches: number;
	description_en?: string;
	description_fr?: string;
	description_ja?: string;
	description_zh?: string;
	description_ar?: string;
	description_ru?: string;
	thumbnail?: SearchThumbnail;
}

export type SearchHit = FeatureHit | ObjectHit | GroupHit | PadHit;

/** What a trip can start or end at — everything but a collection. */
export type EndpointHit = ObjectHit | FeatureHit | PadHit;

// A dead search bar is indistinguishable from a healthy site: the UI renders its
// disabled state and nothing throws. Say why, once, so the cause is one console
// line rather than a bisect.
let warned = false;
function warnOnce(reason: string) {
	if (warned) return;
	warned = true;
	console.warn(`[search] unavailable: ${reason}`);
}

// The Meilisearch SDK (~40 kB gzip) is dynamically imported so it splits out of
// the main map chunk — it only loads once the user actually searches.
let client: Meilisearch | null = null;
async function getClient(): Promise<Meilisearch | null> {
	if (!isSearchEnabled()) return null;
	if (!client) {
		const { Meilisearch } = await import('meilisearch');
		client = new Meilisearch({
			host: env.PUBLIC_MEILI_URL,
			apiKey: env.PUBLIC_MEILI_SEARCH_KEY
		});
		// One unawaited probe on first use. Covers what the env check can't:
		// unreachable host, CORS rejection, revoked key, missing index.
		client
			.index(INDEX)
			.getStats()
			.catch((e) => warnOnce(`${env.PUBLIC_MEILI_URL} unreachable — ${e}`));
	}
	return client;
}

/** Enablement is a pure env check — no client instantiation, so callers stay
 *  synchronous and the SDK isn't pulled in just to render the disabled state. */
export function isSearchEnabled(): boolean {
	const enabled = Boolean(env.PUBLIC_MEILI_URL && env.PUBLIC_MEILI_SEARCH_KEY);
	// Runtime vars, so a build that passed CI still ships search dark.
	if (!enabled) warnOnce('PUBLIC_MEILI_URL / PUBLIC_MEILI_SEARCH_KEY are unset');
	return enabled;
}

/** Unified index name. Objects, surface features and group/collection pages
 *  all live in one index, discriminated by `kind`, so a single query ranks
 *  them together. */
const INDEX = 'catalog';

/** Meili's `maxTotalHits` cap — `estimatedTotalHits` is clamped to it, so a
 *  count that reaches it means "this many or more" and is shown as "N+". */
export const MAX_TOTAL_HITS = 1000;

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

function toPadHit(d: RawHit): PadHit {
	const p = (d.pad ?? {}) as RawHit;
	return { ...d, ...p, kind: 'pad', id: String(d.id) } as PadHit;
}

function toHit(d: RawHit): SearchHit {
	if (d.kind === 'group') return toGroupHit(d);
	if (d.kind === 'feature') return toFeatureHit(d);
	if (d.kind === 'pad') return toPadHit(d);
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
	const c = await getClient();
	if (!c || !query.trim()) return [];
	const res = await c.index(INDEX).search(query, { limit, locales: [locale] });
	return (res.hits ?? []).map((h) => toHit(h as RawHit));
}

/**
 * Everywhere a trip can start or end, for the planner's endpoint pickers.
 *
 * Collections are excluded because you cannot depart from or arrive at one —
 * ranking them alongside would spend a short result list on rows that can't be
 * chosen. Pads stay: leaving from one is the whole reason they are indexed.
 */
export async function searchEndpoints(
	query: string,
	locale: string,
	limit: number = 8
): Promise<EndpointHit[]> {
	const c = await getClient();
	if (!c || !query.trim()) return [];
	const res = await c.index(INDEX).search(query, {
		limit,
		locales: [locale],
		filter: 'kind != "group"'
	});
	return (res.hits ?? []).map((h) => toHit(h as RawHit)) as EndpointHit[];
}

/** A group/moon member — usually an object, but an earth-sat zone also lists
 *  the constellations that call it home, and a feature-type page lists surface
 *  features, so a member can be any catalog kind. */
export type MemberHit = ObjectHit | GroupHit | FeatureHit;

/** One page of a group's members from the catalog index. */
export interface GroupMemberPage {
	hits: MemberHit[];
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
	const c = await getClient();
	if (!c) return { hits: [], estimatedTotalHits: 0 };
	const res = await c.index(INDEX).search('', {
		filter,
		sort: MEMBER_SORT,
		offset,
		limit,
		locales: [locale]
	});
	// A pad belongs to no group's member list — it is part of a site page rather
	// than listed by one — so anything that comes back is a mis-tag, not a row.
	const hits = (res.hits ?? [])
		.map((h) => toHit(h as RawHit))
		.filter((h): h is MemberHit => h.kind !== 'pad');
	return { hits, estimatedTotalHits: res.estimatedTotalHits ?? hits.length };
}

// Category roots the indexer leaves untagged in `object.groups` (it tags only
// cat-moons/satellites/probes). Filter on `object.type` instead — mirrors the
// export's "comet classes → comets, else asteroids" split.
const CATEGORY_MEMBER_FILTER: Record<string, string> = {
	'cat-asteroids':
		'object.type IN ["asteroid", "asteroid_inner", "asteroid_main_belt", "asteroid_trojan", "asteroid_centaur", "asteroid_tno"]',
	'cat-comets': 'object.type = "comet"',
	'cat-solar-system': 'kind = "object"'
};

/** A paginated slice of a group's members (small-body class/flag, earth-sat
 *  collection, or a top-level category), ranked notable-first. Empty when search
 *  is unconfigured or the slug tags no objects (e.g. split-comet families, whose
 *  baked member lists are already complete). */
export async function searchGroupMembers(
	slug: string,
	offset: number,
	limit: number,
	locale: string
): Promise<GroupMemberPage> {
	// Feature types tag no object — their members are the features themselves,
	// matched on the IAU code the group index carries for the slug.
	if (slug.startsWith(FEATURE_TYPE_SLUG_PREFIX)) {
		const code = await featureTypeCode(slug);
		if (!code) {
			console.warn(`[search] No IAU code for ${slug} in the group index — no members.`);
			return { hits: [], estimatedTotalHits: 0 };
		}
		return searchMemberPage(`feature.type = "${code}"`, offset, limit, locale);
	}
	// Earth-sat zones (class-*) also surface the constellations that call them
	// home, interleaved with sats by the shared sitelinks_count sort. (Small-body
	// classes share the prefix but no group points at them, so the OR is inert.)
	const memberFilter = slug.startsWith(CLASS_SLUG_PREFIX)
		? `object.groups = "${slug}" OR group.orbit_classes = "${slug}"`
		: `object.groups = "${slug}"`;
	const filter = CATEGORY_MEMBER_FILTER[slug] ?? memberFilter;
	return searchMemberPage(filter, offset, limit, locale);
}

/** A paginated slice of a body's IAU surface features, ranked notable-first —
 *  the same order the feature's own `ft-` type page lists it in. `quad` narrows
 *  to one IAU quadrangle (the Surface tab's hero selection). */
export function searchBodyFeatures(
	bodyId: string,
	offset: number,
	limit: number,
	locale: string,
	quad?: string,
	featureType?: string
): Promise<GroupMemberPage> {
	return searchMemberPage(bodyFeatureFilter(bodyId, quad, featureType), offset, limit, locale);
}

function bodyFeatureFilter(bodyId: string, quad?: string, featureType?: string): string {
	const parts = [`feature.body_id = ${quote(bodyId)}`];
	if (quad) parts.push(`feature.quad = ${quote(quad)}`);
	if (featureType) parts.push(`feature.type = ${quote(featureType)}`);
	return parts.join(' AND ');
}

/** Feature counts per IAU type for one body, narrowed to a quadrangle when one
 *  is picked — the Surface tab's type chips and their tallies. */
export async function bodyFeatureTypeCounts(
	bodyId: string,
	quad?: string
): Promise<Record<string, number>> {
	const c = await getClient();
	if (!c) return {};
	const res = await c.index(INDEX).search('', {
		filter: bodyFeatureFilter(bodyId, quad),
		facets: ['feature.type'],
		limit: 0
	});
	return ((res.facetDistribution ?? {}) as FacetDistribution)['feature.type'] ?? {};
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

// ── faceted catalog search (Option D panel) ──────────────────────────────

/** Active sort. `relevance` uses Meili's default ranking (+ sitelinks
 *  tiebreaker); the rest map to a sortable attribute. */
export type SortId = 'relevance' | 'name' | 'size' | 'brightness' | 'date';

/** Numeric range facets. Values are in display units (km, magnitude H, calendar
 *  year); `RANGE_FIELDS` maps them to the Meili attribute(s)/value. */
export type RangeFacet = 'diameter' | 'magnitude' | 'inception';
export interface RangeBound {
	min?: number;
	max?: number;
}

/** Active once either edge is set. A shared fn, not inlined — the Svelte
 *  compiler mangles the `!= null` parens and derefs a nullish `b`. */
export function hasBound(b: RangeBound | undefined): boolean {
	return b != null && (b.min != null || b.max != null);
}

/** Selected facet values. Array facets are OR within / AND across; the two
 *  small-body flags are plain booleans; ranges AND a min/max on a numeric field. */
export interface CatalogFilters {
	kind?: string[]; // object | feature | group
	type?: string[]; // object.type
	groups?: string[]; // object.groups slugs (orbit class, constellation, …)
	moonHost?: string[]; // object.moon_host — the body a moon orbits
	moonClass?: string[]; // object.moon_class — planetary | minor_planet
	featureType?: string[]; // feature.type codes
	featureBody?: string[]; // feature.body_id — the body a surface feature sits on
	featureQuad?: string[]; // feature.quad — IAU quadrangle code, scoped to one body
	groupType?: string[]; // group.type names (collection kinds)
	neo?: boolean;
	pha?: boolean;
	/** Moons only: carries an IAU name rather than a provisional designation. */
	named?: boolean;
	ranges?: Partial<Record<RangeFacet, RangeBound>>;
}

/** A range facet's Meili attribute, plus how a display value maps onto it. */
interface RangeTarget {
	field: string;
	encode?: (v: number, edge: 'min' | 'max') => number;
}

// `object.inception` is a YYYYMMDD int, so a year widens to its whole span.
const yearSpan = (v: number, edge: 'min' | 'max') =>
	edge === 'min' ? v * 10000 : v * 10000 + 1231;

// A facet with several targets ORs across them: each kind dates by whatever
// field it actually has, so one year slider covers objects (discovery/launch)
// and surface features (IAU name approval) alike.
const RANGE_FIELDS: Record<RangeFacet, RangeTarget[]> = {
	diameter: [{ field: 'diameter_km' }],
	magnitude: [{ field: 'object.magnitude' }],
	inception: [{ field: 'object.inception', encode: yearSpan }, { field: 'feature.named' }]
};

/** A facet value → match-count map, keyed by facet attribute. */
export type FacetDistribution = Record<string, Record<string, number>>;

export interface CatalogResult {
	hits: SearchHit[];
	/** Capped at the index's maxTotalHits (1000). */
	estimatedTotalHits: number;
	facets: FacetDistribution;
}

const FACETS = [
	'kind',
	'object.type',
	'object.groups',
	'object.neo',
	'object.pha',
	'object.moon_host',
	'object.moon_class',
	'object.iau_named',
	'group.type',
	'feature.type',
	'feature.body_id'
	// `feature.quad` is filterable but not faceted — the Surface tab's hero
	// gets its per-cell counts from the exported quadrangle index instead.
];

// Sortable attribute + its "natural" first direction (reversed by the toggle).
const SORT_FIELD: Record<Exclude<SortId, 'relevance'>, [string, boolean]> = {
	name: ['name', false],
	size: ['diameter_km', true],
	brightness: ['object.magnitude', false], // lower H = brighter
	date: ['object.inception', true]
};

function buildSort(sort: SortId, reverse: boolean): string[] {
	if (sort === 'relevance') return [];
	const [field, desc] = SORT_FIELD[sort];
	const dir = reverse ? !desc : desc;
	return [`${field}:${dir ? 'desc' : 'asc'}`];
}

function quote(v: string): string {
	return `"${v.replace(/"/g, '\\"')}"`;
}

function orClause(field: string, vals: string[] | undefined): string | null {
	if (!vals || vals.length === 0) return null;
	return `(${vals.map((v) => `${field} = ${quote(v)}`).join(' OR ')})`;
}

/** Per-facet filter clauses, keyed by the facet attribute. Values within one
 *  facet OR together (inside `orClause`); facets AND when joined. Keyed so a
 *  facet's own clause can be dropped for its disjunctive recount. */
function filterClauses(f: CatalogFilters): Map<string, string> {
	const out = new Map<string, string>();
	const kind = orClause('kind', f.kind);
	if (kind) out.set('kind', kind);
	const type = orClause('object.type', f.type);
	if (type) out.set('object.type', type);
	const groups = orClause('object.groups', f.groups);
	if (groups) out.set('object.groups', groups);
	const moonHost = orClause('object.moon_host', f.moonHost);
	if (moonHost) out.set('object.moon_host', moonHost);
	const moonClass = orClause('object.moon_class', f.moonClass);
	if (moonClass) out.set('object.moon_class', moonClass);
	const featureType = orClause('feature.type', f.featureType);
	if (featureType) out.set('feature.type', featureType);
	const featureBody = orClause('feature.body_id', f.featureBody);
	if (featureBody) out.set('feature.body_id', featureBody);
	const featureQuad = orClause('feature.quad', f.featureQuad);
	if (featureQuad) out.set('feature.quad', featureQuad);
	const groupType = orClause('group.type', f.groupType);
	if (groupType) out.set('group.type', groupType);
	if (f.named) out.set('object.iau_named', 'object.iau_named = true');
	if (f.neo) out.set('object.neo', 'object.neo = true');
	if (f.pha) out.set('object.pha', 'object.pha = true');
	return out;
}

/** Range clauses — always applied (no facet distribution to recount). */
function rangeClauses(f: CatalogFilters): string[] {
	const out: string[] = [];
	for (const [facet, b] of Object.entries(f.ranges ?? {}) as [RangeFacet, RangeBound][]) {
		const perField = RANGE_FIELDS[facet].map(({ field, encode }) => {
			const bits: string[] = [];
			if (b.min != null) bits.push(`${field} >= ${encode ? encode(b.min, 'min') : b.min}`);
			if (b.max != null) bits.push(`${field} <= ${encode ? encode(b.max, 'max') : b.max}`);
			return bits.join(' AND ');
		});
		if (perField.length === 1) out.push(perField[0]);
		else out.push(`(${perField.map((c) => `(${c})`).join(' OR ')})`);
	}
	return out;
}

/** AND the facet clauses (minus `except`) with the always-on `ranges`. */
function joinClauses(
	clauses: Map<string, string>,
	ranges: string[],
	except?: string
): string | undefined {
	const parts = [...clauses].filter(([k]) => k !== except).map(([, v]) => v);
	parts.push(...ranges);
	return parts.length ? parts.join(' AND ') : undefined;
}

/** One page of the faceted catalog: ranked hits, a facet distribution (drives
 *  counts + the filter tree), and the capped total.
 *
 *  Facets are disjunctive: each facet that has an active selection gets its
 *  distribution recomputed with its own clause dropped, so its sibling values
 *  keep the true counts you'd get by OR-ing them in — instead of collapsing to
 *  the one selected value. Facets with no selection use the main distribution. */
export async function searchCatalog(opts: {
	query: string;
	filters: CatalogFilters;
	sort: SortId;
	reverse: boolean;
	page: number;
	pageSize: number;
	locale: string;
	/** When false, fetch only hits (skip the facet recount) — used by infinite
	 *  scroll for pages past the first, where facets/total are already known. */
	facets?: boolean;
}): Promise<CatalogResult> {
	const c = await getClient();
	if (!c) return { hits: [], estimatedTotalHits: 0, facets: {} };
	const sort = buildSort(opts.sort, opts.reverse);
	const clauses = filterClauses(opts.filters);
	const ranges = rangeClauses(opts.filters);
	const active = [...clauses.keys()];

	// Hits-only fast path: one plain search, no facet recount fan-out.
	if (opts.facets === false) {
		const res = await c.index(INDEX).search(opts.query, {
			filter: joinClauses(clauses, ranges),
			sort: sort.length ? sort : undefined,
			offset: (opts.page - 1) * opts.pageSize,
			limit: opts.pageSize,
			locales: [opts.locale]
		});
		return {
			hits: (res.hits ?? []).map((h) => toHit(h as RawHit)),
			estimatedTotalHits: res.estimatedTotalHits ?? 0,
			facets: {}
		};
	}

	const { results } = await c.multiSearch({
		queries: [
			{
				indexUid: INDEX,
				q: opts.query,
				filter: joinClauses(clauses, ranges),
				sort: sort.length ? sort : undefined,
				facets: FACETS,
				offset: (opts.page - 1) * opts.pageSize,
				limit: opts.pageSize,
				locales: [opts.locale]
			},
			// One recount per selected facet: same query, all clauses except its own.
			...active.map((facet) => ({
				indexUid: INDEX,
				q: opts.query,
				filter: joinClauses(clauses, ranges, facet),
				facets: [facet],
				limit: 0,
				locales: [opts.locale]
			}))
		]
	});

	const main = results[0];
	const facets: FacetDistribution = { ...((main.facetDistribution ?? {}) as FacetDistribution) };
	active.forEach((facet, i) => {
		facets[facet] = ((results[i + 1].facetDistribution ?? {}) as FacetDistribution)[facet] ?? {};
	});

	return {
		hits: (main.hits ?? []).map((h) => toHit(h as RawHit)),
		estimatedTotalHits: main.estimatedTotalHits ?? 0,
		facets
	};
}

// Unfiltered facet distribution over the whole catalog, cached after first use.
// Supplies the full value vocabulary so bounded facets (kind, type, flags) can
// still list every option — at 0 — once a query/filter narrows them away.
let facetUniverseCache: FacetDistribution | null = null;

export async function catalogFacets(): Promise<FacetDistribution> {
	if (facetUniverseCache) return facetUniverseCache;
	const c = await getClient();
	if (!c) return {};
	const res = await c.index(INDEX).search('', { facets: FACETS, limit: 0 });
	facetUniverseCache = (res.facetDistribution ?? {}) as FacetDistribution;
	return facetUniverseCache;
}

// Total documents in the catalog, cached after the first stats call. Drives the
// idle "N entries in catalog" hint (estimatedTotalHits caps at maxTotalHits).
// Returns null when the index can't be reached (env unset or server down) so the
// hint can read "catalog unavailable" instead of a misleading "0 entries". The
// failure isn't cached, so a later call retries once the DB is back.
let catalogCountCache: number | null = null;

export async function catalogCount(): Promise<number | null> {
	if (catalogCountCache !== null) return catalogCountCache;
	const c = await getClient();
	if (!c) return null;
	try {
		const stats = await c.index(INDEX).getStats();
		catalogCountCache = stats.numberOfDocuments ?? 0;
		return catalogCountCache;
	} catch {
		return null;
	}
}

// Every group/collection doc, fetched once per locale to label the filter
// tree (slug → name/type) without a round-trip per facet value. ~830 docs.
const groupCatalogCache = new Map<string, GroupHit[]>();

export async function fetchGroupCatalog(locale: string): Promise<GroupHit[]> {
	const cached = groupCatalogCache.get(locale);
	if (cached) return cached;
	const c = await getClient();
	if (!c) return [];
	const res = await c.index(INDEX).search('', {
		filter: 'kind = "group"',
		sort: ['group.member_count:desc'],
		limit: 1000,
		locales: [locale]
	});
	const groups = (res.hits ?? []).map((h) => toGroupHit(h as RawHit));
	groupCatalogCache.set(locale, groups);
	return groups;
}

// Object id → localized name, filled on demand. Filter leaves are labelled by
// id (a facet value), and the scene only knows bodies it has loaded — most
// minor planets aren't among them — so names come from the catalog instead.
const objectNameCache = new Map<string, string>();

/** Localized names for the given object ids, from cache plus one batched
 *  lookup for the rest. Ids the catalog doesn't carry are simply absent. */
export async function fetchObjectNames(
	ids: string[],
	locale: string
): Promise<Map<string, string>> {
	const missing = ids.filter((id) => !objectNameCache.has(`${locale}:${id}`));
	if (missing.length) {
		const c = await getClient();
		if (!c) return new Map();
		const res = await c.index(INDEX).search('', {
			filter: `object.id IN [${missing.map(quote).join(', ')}]`,
			limit: missing.length,
			locales: [locale]
		});
		for (const raw of res.hits ?? []) {
			const hit = toObjectHit(raw as RawHit);
			objectNameCache.set(`${locale}:${hit.id}`, localizedName(hit, locale));
		}
		// Most minor planets with a moon are too obscure to be indexed
		// themselves, so a second pass reads the host name their moons carry.
		const stillMissing = missing.filter((id) => !objectNameCache.has(`${locale}:${id}`));
		if (stillMissing.length) {
			const moons = await c.index(INDEX).search('', {
				filter: `object.moon_host IN [${stillMissing.map(quote).join(', ')}]`,
				limit: 1000,
				locales: [locale]
			});
			for (const raw of moons.hits ?? []) {
				const o = ((raw as RawHit).object ?? {}) as RawHit;
				const host = o.moon_host as string | undefined;
				const name = o.moon_host_name as string | undefined;
				if (host && name) objectNameCache.set(`${locale}:${host}`, name);
			}
		}
		// Blank-cache what neither pass could name, so a re-render doesn't
		// re-query it forever.
		for (const id of missing) {
			const key = `${locale}:${id}`;
			if (!objectNameCache.has(key)) objectNameCache.set(key, '');
		}
	}
	const out = new Map<string, string>();
	for (const id of ids) {
		const name = objectNameCache.get(`${locale}:${id}`);
		if (name) out.set(id, name);
	}
	return out;
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
