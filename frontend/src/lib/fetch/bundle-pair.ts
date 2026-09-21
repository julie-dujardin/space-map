/**
 * Hash-bucketed `{global, localized}` bundle pairs — objects, IAU features and
 * collections all ship in this shape, so one descriptor per content class
 * drives both the client loaders and their SSR twins.
 *
 * {@link loadBundlePair} takes its fetcher and its metadata as arguments: SEO
 * loads run per request against an absolute origin and must not touch the
 * client's module-singleton caches.
 */

import { fetchMetadata, hashBucket } from '$lib/fetch/metadata';
import { fetchGzipBundle } from '$lib/fetch/bundle-cache';
import { dataBase, versionedUrl } from '$lib/fetch/data-base';

/** The `metadata.json` fields a bundle pair reads; `Metadata` satisfies it. */
export interface BundleMetadata {
	object_bundles?: Record<string, number>;
	feature_bundles?: Record<string, number>;
	group_bundles?: Record<string, number>;
	versions?: Record<string, string>;
}

export interface BundlePairDescriptor {
	/** `metadata.json` key holding this class's bucket counts. */
	counts: 'object_bundles' | 'feature_bundles' | 'group_bundles';
	globalPath: (bucket: number) => string;
	localizedPath: (lang: string, bucket: number) => string;
	/** Cache-busting content class, omitted where the export carries no token. */
	versionClass?: string;
}

export const OBJECT_BUNDLES: BundlePairDescriptor = {
	counts: 'object_bundles',
	globalPath: (b) => `/v1/objects/__global__/${b}.json.gz`,
	localizedPath: (lang, b) => `/v1/objects/${lang}/${b}.json.gz`,
	versionClass: 'objects'
};

export const FEATURE_BUNDLES: BundlePairDescriptor = {
	counts: 'feature_bundles',
	globalPath: (b) => `/v1/nomenclature/details/__global__/${b}.json.gz`,
	localizedPath: (lang, b) => `/v1/nomenclature/details/${lang}/${b}.json.gz`,
	versionClass: 'nomenclature'
};

/** Group bundles are unversioned by design. */
export const GROUP_BUNDLES: BundlePairDescriptor = {
	counts: 'group_bundles',
	globalPath: (b) => `/v1/groups/__global__/${b}.json.gz`,
	localizedPath: (lang, b) => `/v1/groups/${lang}/${b}.json.gz`
};

export interface BundlePair<G, L> {
	global: G | null;
	localized: L | null;
}

/** Reads one bundle from a data-root-relative path; `null` when absent. */
export type BundleFetcher = (
	path: string,
	versionClass: string | undefined
) => Promise<Record<string, unknown> | null>;

/** Client-side: shared LRU, `?v=` token from the live version map. */
const clientFetcher: BundleFetcher = (path, versionClass) =>
	fetchGzipBundle<unknown>(
		versionClass ? versionedUrl(path, versionClass) : `${dataBase()}${path}`
	);

/** Prefetches queue behind the scene's own boot fetches rather than beside
 *  them — the panel they feed cannot be read until the map is up anyway. */
const prefetchFetcher: BundleFetcher = (path, versionClass) =>
	fetchGzipBundle<unknown>(
		versionClass ? versionedUrl(path, versionClass) : `${dataBase()}${path}`,
		{ priority: 'low' }
	);

export interface LoadBundlePairOptions {
	meta: BundleMetadata;
	lang: string;
	fetchBundle: BundleFetcher;
	/** False skips the localized bundle, for keys known to lack one. */
	localized?: boolean;
}

/**
 * Fetch and index both bundles holding `key`. Either half is null when its
 * bundle, or the entry inside it, is missing — callers decide what that means.
 */
export async function loadBundlePair<G, L>(
	desc: BundlePairDescriptor,
	key: string,
	{ meta, lang, fetchBundle, localized = true }: LoadBundlePairOptions
): Promise<BundlePair<G, L>> {
	const counts = meta[desc.counts];
	// A zero or absent count means the export has no such bundles; bucketing
	// against it would yield a bogus index (or divide by zero).
	const nGlobal = counts?.global ?? 0;
	const nLocalized = localized ? (counts?.[lang] ?? 0) : 0;

	const [globalBucket, localizedBucket] = await Promise.all([
		nGlobal ? hashBucket(key, nGlobal) : -1,
		nLocalized ? hashBucket(key, nLocalized) : -1
	]);

	const [globalBundle, localizedBundle] = await Promise.all([
		globalBucket >= 0 ? fetchBundle(desc.globalPath(globalBucket), desc.versionClass) : null,
		localizedBucket >= 0
			? fetchBundle(desc.localizedPath(lang, localizedBucket), desc.versionClass)
			: null
	]);

	return {
		global: (globalBundle?.[key] as G | undefined) ?? null,
		localized: (localizedBundle?.[key] as L | undefined) ?? null
	};
}

/**
 * Warm the bucket holding `key` so a later {@link fetchBundlePair} finds the
 * request in flight rather than starting one. Only the global half: it is the
 * bulk of the payload (object buckets run to ~1MB gzipped against ~180KB for a
 * localized one), and whether a key even has a localized entry is not known
 * until its body has streamed in.
 */
export async function prefetchBundlePair(desc: BundlePairDescriptor, key: string): Promise<void> {
	const meta = await fetchMetadata();
	const nGlobal = meta[desc.counts]?.global ?? 0;
	if (!nGlobal) return;
	const bucket = await hashBucket(key, nGlobal);
	// Failures are the real load's to report — this one only fills the cache.
	await prefetchFetcher(desc.globalPath(bucket), desc.versionClass).catch(() => null);
}

/** Client entry point: memoized metadata, cached bundles. */
export async function fetchBundlePair<G, L>(
	desc: BundlePairDescriptor,
	key: string,
	lang: string,
	localized = true
): Promise<BundlePair<G, L>> {
	const meta = await fetchMetadata();
	return loadBundlePair<G, L>(desc, key, {
		meta,
		lang,
		localized,
		fetchBundle: clientFetcher
	});
}
