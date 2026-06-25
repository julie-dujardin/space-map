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
 *  The `f` grammar is `;`-separated facets, each `token:val,val`, a range
 *  `token:lo..hi`, or a bare `neo`/`pha` flag. Values are ascii, round-tripped raw. */

import { hasBound, type CatalogFilters, type RangeFacet, type SortId } from './client';

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

// Numeric range facet ↔ short URL token; serialized as `token:lo..hi` (either
// bound may be empty: `mag:..15`, `date:1990..`). Values are display units.
const RANGE_FACETS: [RangeFacet, string][] = [
	['diameter', 'diameter'],
	['magnitude', 'mag'],
	['inception', 'date']
];
const RANGE_TOKEN_TO_FACET = new Map(RANGE_FACETS.map(([f, t]) => [t, f]));

const SORTS: SortId[] = ['relevance', 'name', 'size', 'brightness', 'date'];

/** Parse a URL number field; '' / non-finite → undefined. */
function num(s: string): number | undefined {
	const t = s.trim();
	if (t === '') return undefined;
	const v = Number(t);
	return Number.isFinite(v) ? v : undefined;
}

/** True when the search has anything worth putting in the URL. */
export function searchActive(s: SearchUrlState): boolean {
	if (s.query.trim()) return true;
	const f = s.filters;
	const hasRange = Object.values(f.ranges ?? {}).some(hasBound);
	return Boolean(
		f.kind?.length ||
		f.type?.length ||
		f.groups?.length ||
		f.featureType?.length ||
		f.groupType?.length ||
		f.neo ||
		f.pha ||
		hasRange
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
	for (const [facet, token] of RANGE_FACETS) {
		const b = s.filters.ranges?.[facet];
		if (!hasBound(b)) continue;
		seg.push(`${token}:${b!.min ?? ''}..${b!.max ?? ''}`);
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
			const name = seg.slice(0, colon);
			const rawVal = seg.slice(colon + 1);

			const facet = RANGE_TOKEN_TO_FACET.get(name);
			if (facet) {
				const dots = rawVal.indexOf('..');
				if (dots < 0) continue;
				const min = num(rawVal.slice(0, dots));
				const max = num(rawVal.slice(dots + 2));
				if (min != null || max != null) (filters.ranges ??= {})[facet] = { min, max };
				continue;
			}

			const key = TOKEN_TO_KEY.get(name);
			if (!key) continue;
			const vals = rawVal.split(',').map(decodeURIComponent).filter(Boolean);
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
