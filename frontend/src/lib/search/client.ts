/** Thin Meilisearch wrapper for the search bar.
 *  Returns an empty hit list when the env isn't configured, so the UI can
 *  render a disabled state without special-casing the absence. */

import { Meilisearch } from 'meilisearch';
import { PUBLIC_MEILI_URL, PUBLIC_MEILI_SEARCH_KEY } from '$env/static/public';

export interface FeatureHit {
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

export async function searchFeatures(
	query: string,
	locale: string,
	limit: number = 8
): Promise<FeatureHit[]> {
	const c = getClient();
	if (!c || !query.trim()) return [];
	const res = await c.index<FeatureHit>('features').search(query, {
		limit,
		locales: [locale]
	});
	return res.hits;
}

/** Display name for a hit in the active locale, falling back to canonical. */
export function localizedName(hit: FeatureHit, locale: string): string {
	const field = `name_${locale}` as keyof FeatureHit;
	const v = hit[field];
	if (typeof v === 'string' && v) return v;
	return hit.name;
}
