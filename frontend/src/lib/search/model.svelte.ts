/** Reactive controller for the search panel. Results page in a sliding window
 *  for infinite scroll: chunks load around the viewport, far chunks evict. */

import {
	searchCatalog,
	hasBound,
	type CatalogFilters,
	type FacetDistribution,
	type RangeBound,
	type RangeFacet,
	type SearchHit,
	type SortId
} from './client';

// Hits per page; fixed so the page↔offset mapping stays stable.
export const CHUNK = 20;
/** Max pages kept loaded at once; the window slides and evicts the far end. */
const WINDOW = 4;

/** A removable applied-filter chip. `value` is unset for the boolean flags; for
 *  a range chip `key` is 'ranges' and `value` is the `RangeFacet`. */
export interface FilterToken {
	key: keyof CatalogFilters;
	value?: string;
	label: string;
}

export type ArrayFacet =
	| 'kind'
	| 'type'
	| 'groups'
	| 'moonHost'
	| 'moonClass'
	| 'featureType'
	| 'featureBody'
	| 'groupType';
export type BoolFacet = 'neo' | 'pha' | 'named';
export type { RangeFacet };

/** Sort options in menu order; labels resolve via `search_sort_*` messages. */
export const SORTS: { id: SortId; key: string }[] = [
	{ id: 'relevance', key: 'search_sort_relevance' },
	{ id: 'name', key: 'search_sort_name' },
	{ id: 'size', key: 'search_sort_size' },
	{ id: 'brightness', key: 'search_sort_brightness' },
	{ id: 'date', key: 'search_sort_date' }
];

// Inputs frozen at reset so all pages of a scroll share one filter set.
interface Snapshot {
	query: string;
	filters: CatalogFilters;
	sort: SortId;
	reverse: boolean;
	locale: string;
}

function countActive(f: CatalogFilters): number {
	let n =
		(f.kind?.length ?? 0) +
		(f.type?.length ?? 0) +
		(f.groups?.length ?? 0) +
		(f.moonHost?.length ?? 0) +
		(f.moonClass?.length ?? 0) +
		(f.featureType?.length ?? 0) +
		(f.featureBody?.length ?? 0) +
		(f.groupType?.length ?? 0);
	if (f.named) n++;
	if (f.neo) n++;
	if (f.pha) n++;
	for (const b of Object.values(f.ranges ?? {})) if (hasBound(b)) n++;
	return n;
}

export class SearchModel {
	query = $state('');
	filters = $state<CatalogFilters>({});
	sort = $state<SortId>('relevance');
	reverse = $state(false);
	// Anchor page dominant in the viewport — mirrored to the URL.
	page = $state(1);
	pageSize = CHUNK;

	// Loaded chunks keyed by 1-based page; facets/total are page-independent.
	pages = $state<Map<number, SearchHit[]>>(new Map());
	total = $state(0);
	facets = $state<FacetDistribution>({});
	loading = $state(false);
	// Last query threw (index down/unreachable) — drives the error state instead
	// of a misleading "no matches".
	error = $state(false);

	// Bumped on every reset; loads tag themselves with it and drop if stale.
	#gen = 0;
	#active: Snapshot | null = null;
	// Pages currently being fetched (this generation) — dedupes concurrent loads.
	#inflight = new Set<number>();

	activeCount = $derived(countActive(this.filters));
	hasResults = $derived(this.query.trim() !== '' || this.activeCount > 0);
	totalPages = $derived(Math.max(1, Math.ceil(this.total / CHUNK)));

	firstLoaded = $derived(this.pages.size ? Math.min(...this.pages.keys()) : 0);
	lastLoaded = $derived(this.pages.size ? Math.max(...this.pages.keys()) : 0);
	// Item offset of the first loaded hit — the view's top spacer height.
	firstIndex = $derived(this.firstLoaded > 0 ? (this.firstLoaded - 1) * CHUNK : 0);

	// Loaded hits flattened in page order (the window is always contiguous).
	hits = $derived.by((): SearchHit[] => {
		const out: SearchHit[] = [];
		for (let p = this.firstLoaded; p > 0 && p <= this.lastLoaded; p++) {
			const arr = this.pages.get(p);
			if (arr) out.push(...arr);
		}
		return out;
	});

	/** Reset the window and load the anchor page. Snapshot in, no reactive reads. */
	runSearch(snapshot: Snapshot): void {
		const gen = ++this.#gen;
		this.#inflight.clear();
		this.#active = snapshot;
		this.pages = new Map();
		this.error = false;
		if (!snapshot.query.trim() && countActive(snapshot.filters) === 0) {
			this.total = 0;
			this.facets = {};
			this.loading = false;
			this.page = 1;
			return;
		}
		// Anchor = hydrated page (else 1), fetched with facets to populate the tree.
		void this.#load(Math.max(1, this.page), true, gen);
	}

	/** Fetch one page into the window, evicting the far end past `WINDOW`. */
	async #load(pageNo: number, withFacets: boolean, gen: number): Promise<void> {
		if (pageNo < 1 || gen !== this.#gen) return;
		if (this.pages.has(pageNo) || this.#inflight.has(pageNo)) return;
		const snap = this.#active;
		if (!snap) return;
		this.#inflight.add(pageNo);
		this.loading = true;
		try {
			const res = await searchCatalog({
				...snap,
				page: pageNo,
				pageSize: CHUNK,
				facets: withFacets
			});
			if (gen !== this.#gen) return;
			const next = new Map(this.pages);
			next.set(pageNo, res.hits);
			// Cap at WINDOW pages: drop whichever end is farther from this load.
			while (next.size > WINDOW) {
				const keys = [...next.keys()];
				const lo = Math.min(...keys);
				const hi = Math.max(...keys);
				next.delete(pageNo - lo >= hi - pageNo ? lo : hi);
			}
			this.pages = next;
			if (withFacets) {
				this.facets = res.facets;
				this.total = res.estimatedTotalHits;
			}
			this.error = false;
		} catch (err) {
			if (gen !== this.#gen) return;
			console.warn('[search] catalog query failed:', err);
			if (this.pages.size === 0) this.error = true;
		} finally {
			this.#inflight.delete(pageNo);
			if (gen === this.#gen && this.#inflight.size === 0) this.loading = false;
		}
	}

	/** Extend the window forward one page (no-op past the last page). */
	ensureNext(): void {
		if (!this.#active || this.lastLoaded === 0) return;
		const next = this.lastLoaded + 1;
		if (next <= this.totalPages) void this.#load(next, false, this.#gen);
	}

	/** Extend the window backward one page (no-op at the top). */
	ensurePrev(): void {
		if (!this.#active || this.firstLoaded <= 1) return;
		void this.#load(this.firstLoaded - 1, false, this.#gen);
	}

	setQuery(q: string): void {
		this.query = q;
		this.page = 1;
	}

	setSort(s: SortId): void {
		if (this.sort === s) return;
		this.sort = s;
		this.page = 1;
	}

	toggleReverse(): void {
		this.reverse = !this.reverse;
		this.page = 1;
	}

	/** Mirror the scroll-derived anchor page for the URL; no refetch. */
	setAnchor(p: number): void {
		const clamped = Math.min(Math.max(1, p), this.totalPages);
		if (clamped !== this.page) this.page = clamped;
	}

	/** Toggle a set of values on an array facet as a unit (a merged leaf such as
	 *  "Asteroid" maps to several raw `object.type` values). */
	toggleValues(key: ArrayFacet, values: string[]): void {
		const cur = new Set(this.filters[key] ?? []);
		const allIn = values.every((v) => cur.has(v));
		for (const v of values) {
			if (allIn) cur.delete(v);
			else cur.add(v);
		}
		this.filters = { ...this.filters, [key]: [...cur] };
		this.page = 1;
	}

	isChecked(key: ArrayFacet, values: string[]): boolean {
		const cur = this.filters[key] ?? [];
		return values.length > 0 && values.every((v) => cur.includes(v));
	}

	toggleBool(key: BoolFacet): void {
		this.filters = { ...this.filters, [key]: this.filters[key] ? undefined : true };
		this.page = 1;
	}

	rangeOf(facet: RangeFacet): RangeBound {
		return this.filters.ranges?.[facet] ?? {};
	}

	/** Set a range's min/max (undefined edge = unbounded); empty bound clears it. */
	setRange(facet: RangeFacet, bound: RangeBound): void {
		const ranges = { ...this.filters.ranges };
		if (bound.min == null && bound.max == null) delete ranges[facet];
		else ranges[facet] = bound;
		this.filters = { ...this.filters, ranges };
		this.page = 1;
	}

	clearRange(facet: RangeFacet): void {
		this.setRange(facet, {});
	}

	removeToken(t: FilterToken): void {
		if (t.key === 'neo' || t.key === 'pha' || t.key === 'named') this.toggleBool(t.key);
		else if (t.key === 'ranges' && t.value != null) this.clearRange(t.value as RangeFacet);
		else if (t.value != null) this.toggleValues(t.key as ArrayFacet, [t.value]);
		this.page = 1;
	}

	clearFilters(): void {
		this.filters = {};
		this.page = 1;
	}

	reset(): void {
		this.query = '';
		this.filters = {};
		this.sort = 'relevance';
		this.reverse = false;
		this.page = 1;
		this.pages = new Map();
		this.total = 0;
		this.facets = {};
		this.error = false;
		this.#gen++;
	}

	/** Restore query/filters/sort/page from a URL-parsed snapshot (hydration). */
	applyUrlState(s: {
		query: string;
		filters: CatalogFilters;
		sort: SortId;
		reverse: boolean;
		page: number;
	}): void {
		this.query = s.query;
		this.filters = s.filters;
		this.sort = s.sort;
		this.reverse = s.reverse;
		this.page = s.page;
	}
}
