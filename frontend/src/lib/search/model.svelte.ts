/** Reactive controller for the Option D search panel.
 *  Holds query/filter/sort/page state; the orchestrator runs `runQuery` from a
 *  debounced $effect (snapshot args in, result out — no read/write loop). */

import {
	searchCatalog,
	hasBound,
	type CatalogFilters,
	type CatalogResult,
	type RangeBound,
	type RangeFacet,
	type SortId
} from './client';

const EMPTY: CatalogResult = { hits: [], estimatedTotalHits: 0, facets: {} };

/** A removable applied-filter chip. `value` is unset for the boolean flags; for
 *  a range chip `key` is 'ranges' and `value` is the `RangeFacet`. */
export interface FilterToken {
	key: keyof CatalogFilters;
	value?: string;
	label: string;
}

export type ArrayFacet = 'kind' | 'type' | 'groups' | 'featureType' | 'groupType';
export type BoolFacet = 'neo' | 'pha';
export type { RangeFacet };

/** Sort options in menu order; labels resolve via `search_sort_*` messages. */
export const SORTS: { id: SortId; key: string }[] = [
	{ id: 'relevance', key: 'search_sort_relevance' },
	{ id: 'name', key: 'search_sort_name' },
	{ id: 'size', key: 'search_sort_size' },
	{ id: 'brightness', key: 'search_sort_brightness' },
	{ id: 'date', key: 'search_sort_date' }
];

function countActive(f: CatalogFilters): number {
	let n =
		(f.kind?.length ?? 0) +
		(f.type?.length ?? 0) +
		(f.groups?.length ?? 0) +
		(f.featureType?.length ?? 0) +
		(f.groupType?.length ?? 0);
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
	page = $state(1);
	pageSize = $state(8);
	result = $state<CatalogResult>(EMPTY);
	loading = $state(false);
	// Last query threw (index down/unreachable) — drives the error state instead
	// of a misleading "no matches".
	error = $state(false);

	#token = 0;

	activeCount = $derived(countActive(this.filters));
	hasResults = $derived(this.query.trim() !== '' || this.activeCount > 0);
	pageCount = $derived(Math.max(1, Math.ceil(this.result.estimatedTotalHits / this.pageSize)));

	/** Run the query for a captured snapshot. Token-guarded so stale responses
	 *  lose; reads no $state for inputs and writes only result/loading. */
	async runQuery(snapshot: {
		query: string;
		filters: CatalogFilters;
		sort: SortId;
		reverse: boolean;
		page: number;
		pageSize: number;
		locale: string;
	}): Promise<void> {
		const token = ++this.#token;
		if (!snapshot.query.trim() && countActive(snapshot.filters) === 0) {
			this.result = EMPTY;
			this.error = false;
			this.loading = false;
			return;
		}
		this.loading = true;
		try {
			const res = await searchCatalog(snapshot);
			if (token !== this.#token) return;
			this.result = res;
			this.error = false;
		} catch (err) {
			if (token !== this.#token) return;
			console.warn('[search] catalog query failed:', err);
			this.result = EMPTY;
			this.error = true;
		} finally {
			if (token === this.#token) this.loading = false;
		}
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

	setPage(p: number): void {
		this.page = Math.min(Math.max(1, p), this.pageCount);
	}

	/** Resize the page to fill the visible panel; clamps the current page so it
	 *  stays in range under the new count. */
	setPageSize(n: number): void {
		if (n === this.pageSize || n < 1) return;
		this.pageSize = n;
		const pages = Math.max(1, Math.ceil(this.result.estimatedTotalHits / n));
		this.page = Math.min(this.page, pages);
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
		if (t.key === 'neo' || t.key === 'pha') this.toggleBool(t.key);
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
		this.result = EMPTY;
		this.error = false;
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
