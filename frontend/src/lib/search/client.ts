/** Thin Meilisearch wrapper for the search bar.
 *  Returns an empty hit list when the env isn't configured, so the UI can
 *  render a disabled state without special-casing the absence. */

import { Meilisearch } from 'meilisearch';
import { PUBLIC_MEILI_URL, PUBLIC_MEILI_SEARCH_KEY } from '$env/static/public';

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
	name_en?: string;
	name_fr?: string;
	name_ja?: string;
	name_zh?: string;
	name_ar?: string;
	name_ru?: string;
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

/** Federated search across groups + objects + features. Groups are a small,
 *  curated set of high-intent matches (constellations, operators, ...) and
 *  lead the result list ahead of any object/feature hits, which are then
 *  round-robined to mix the two indices fairly. */
export async function search(
	query: string,
	locale: string,
	limit: number = 8
): Promise<SearchHit[]> {
	const c = getClient();
	if (!c || !query.trim()) return [];
	const res = await c.multiSearch({
		queries: [
			{ indexUid: 'groups', q: query, limit, locales: [locale] },
			{ indexUid: 'objects', q: query, limit, locales: [locale] },
			{ indexUid: 'features', q: query, limit, locales: [locale] }
		]
	});
	const groups = (res.results[0]?.hits ?? []).map(
		(h) => ({ ...h, kind: 'group', id: (h as { slug: string }).slug }) as GroupHit
	);
	const objects = (res.results[1]?.hits ?? []).map((h) => ({ ...h, kind: 'object' }) as ObjectHit);
	const features = (res.results[2]?.hits ?? []).map(
		(h) => ({ ...h, kind: 'feature' }) as FeatureHit
	);
	return [...groups, ...interleave(objects, features)].slice(0, limit);
}

/** Round-robin two ranked lists into one. Cheap stand-in for cross-index
 *  score normalization, which Meili doesn't expose. */
function interleave<A, B>(a: A[], b: B[]): (A | B)[] {
	const out: (A | B)[] = [];
	const n = Math.max(a.length, b.length);
	for (let i = 0; i < n; i++) {
		if (i < a.length) out.push(a[i]);
		if (i < b.length) out.push(b[i]);
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
