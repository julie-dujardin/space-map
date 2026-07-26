import { error } from '@sveltejs/kit';
import { browser } from '$app/environment';
import { FEATURE_ROUTE_TYPES } from '$lib/state/view';
import { loadFeatureSeo, minimalSeo } from '$lib/seo/meta';
import type { PageLoad } from './$types';

// URL type segment → object id prefix, for the body a feature hangs off.
// Mirrors urlTypeToIdPrefix in url.ts (not imported: that module pulls in
// client-only $app/state).
const TYPE_TO_PREFIX: Record<string, string> = {
	b: 'naif',
	s: 'spkid',
	e: 'norad_satcat',
	p: 'probe',
	u: 'extra'
};

export const load: PageLoad = async ({ params, url }) => {
	// Features hang off a body — 404 any non-body type segment.
	if (!FEATURE_ROUTE_TYPES.has(params.type)) {
		error(404, `Unknown type segment "${params.type}"`);
	}

	// Meta matters only for the server-rendered document; client navigations let
	// MapPage own the head, so skip the fetch there.
	if (browser) return { seo: null };
	const name = params.name ? decodeURIComponent(params.name) : '';
	const fallback = () => minimalSeo(name, url.origin, url.pathname);

	const prefix = TYPE_TO_PREFIX[params.type];
	const featureId = Number(params.featureId);
	if (!prefix || !Number.isFinite(featureId)) return { seo: fallback() };

	const seo = await loadFeatureSeo(
		`${prefix}-${params.id}`,
		featureId,
		name,
		url.origin,
		url.pathname
	);
	return { seo: seo ?? fallback() };
};
