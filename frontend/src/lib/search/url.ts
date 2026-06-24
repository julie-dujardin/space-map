/** Serialize/parse the search panel's state to/from the URL query string.
 *
 *  Search is ephemeral: written with replaceState only (never pushed into
 *  history) and restored on a fresh load / shared link, not via back/forward.
 *
 *  Layout — a small, stable set of keys so they're easy to spot and clear:
 *    q=<text>                       full-text query
 *    f=type:moon,comet;groups:country-us;neo   facet filters
 *    sort=<id>&dir=desc             non-default sort (dir only when reversed)
 *    page=<n>                       page > 1
 *
 *  The `f` grammar is `;`-separated facets, each `token:val,val` (or a bare
 *  `neo`/`pha` flag). Values are ascii slugs/codes, so they round-trip raw; a
 *  future range facet slots in as `diameter:10..100` with no format change. */

import type { CatalogFilters, SortId } from './client';

export interface SearchUrlState {
	query: string;
	filters: CatalogFilters;
	sort: SortId;
	reverse: boolean;
	page: number;
}

// Array-facet CatalogFilters key ↔ short URL token; this order is the `f=`
// segment order. The two boolean flags (neo/pha) serialize as bare tokens.
const ARRAY_FACETS: [keyof CatalogFilters, string][] = [
	['kind', 'kind'],
	['type', 'type'],
	['groups', 'groups'],
	['featureType', 'ftype'],
	['groupType', 'gtype']
];
const TOKEN_TO_KEY = new Map(ARRAY_FACETS.map(([k, t]) => [t, k]));

const SORTS: SortId[] = ['relevance', 'name', 'size', 'brightness', 'date'];

/** True when the search has anything worth putting in the URL. */
export function searchActive(s: SearchUrlState): boolean {
	if (s.query.trim()) return true;
	const f = s.filters;
	return Boolean(
		f.kind?.length ||
		f.type?.length ||
		f.groups?.length ||
		f.featureType?.length ||
		f.groupType?.length ||
		f.neo ||
		f.pha
	);
}

/** The `&q=…&f=…` query-string suffix to append after the view's `?at=…` block,
 *  or '' when nothing is active. Always starts with `&` (the view always emits
 *  `?at=`), so it's safe to concatenate. */
export function serializeSearchSuffix(s: SearchUrlState | null | undefined): string {
	if (!s || !searchActive(s)) return '';
	const parts: string[] = [];

	const q = s.query.trim();
	if (q) parts.push(`q=${encodeURIComponent(q)}`);

	const seg: string[] = [];
	for (const [key, token] of ARRAY_FACETS) {
		const vals = s.filters[key] as string[] | undefined;
		if (vals && vals.length) seg.push(`${token}:${vals.map(encodeURIComponent).join(',')}`);
	}
	if (s.filters.neo) seg.push('neo');
	if (s.filters.pha) seg.push('pha');
	if (seg.length) parts.push(`f=${seg.join(';')}`);

	if (s.sort !== 'relevance') {
		parts.push(`sort=${s.sort}`);
		if (s.reverse) parts.push('dir=desc');
	}
	if (s.page > 1) parts.push(`page=${s.page}`);

	return parts.length ? `&${parts.join('&')}` : '';
}

/** Parse search state back out of a URL's query params, or null when no search
 *  is encoded. Unknown facet tokens / sorts are ignored, not errors. */
export function parseSearchSuffix(params: URLSearchParams): SearchUrlState | null {
	const filters: CatalogFilters = {};
	const f = params.get('f');
	if (f) {
		for (const segRaw of f.split(';')) {
			const seg = segRaw.trim();
			if (!seg) continue;
			if (seg === 'neo') {
				filters.neo = true;
				continue;
			}
			if (seg === 'pha') {
				filters.pha = true;
				continue;
			}
			const colon = seg.indexOf(':');
			if (colon < 0) continue;
			const key = TOKEN_TO_KEY.get(seg.slice(0, colon));
			if (!key) continue;
			const vals = seg
				.slice(colon + 1)
				.split(',')
				.map(decodeURIComponent)
				.filter(Boolean);
			if (vals.length) (filters as Record<string, string[]>)[key] = vals;
		}
	}

	const sortRaw = params.get('sort');
	const sort: SortId =
		sortRaw && SORTS.includes(sortRaw as SortId) ? (sortRaw as SortId) : 'relevance';
	const reverse = sort !== 'relevance' && params.get('dir') === 'desc';
	const pageNum = Number(params.get('page'));
	const page = Number.isInteger(pageNum) && pageNum > 1 ? pageNum : 1;

	const state: SearchUrlState = { query: params.get('q') ?? '', filters, sort, reverse, page };
	return searchActive(state) ? state : null;
}
