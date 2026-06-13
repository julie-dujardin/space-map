/**
 * Per-feature detail loader: hash-bucketed JSON bundles, mirroring the
 * objects-pipeline shape. Fetched on drawer open, not eagerly with the
 * marker positions — the eager `fetchBodyNomenclature` call only carries
 * the lean per-body marker metadata.
 *
 * Bucket key: `${bodyId}:${featureId}` (must match `feature_bucket_key`
 * in `data/src/space_map_data/export/nomenclature/writer.py`). Bucket
 * count for each tier ships in `metadata.feature_bundles`.
 */

import { getLocale } from '$lib/paraglide/runtime.js';
import { fetchMetadata, hashBucket } from '$lib/fetch/metadata';
import { versionedUrl } from '$lib/fetch/data-base';
import type {
	CurrencyQuantity,
	EntityRef,
	ObjectImage,
	QuantityWithUnit
} from '$lib/fetch/objects/object-data';

/** Global per-feature payload. Mirrors `_build_detail_global` on the writer. */
export interface FeatureGlobalData {
	/** IAU approval date (ISO yyyy-mm-dd). */
	approval_date?: string;
	/** IAU name-origin / etymology blurb (English; trailing period stripped). */
	origin?: string;
	/** Wikidata QID of the feature itself (drives the "view on Wikidata" link). */
	wikidata_qid?: string;
	/** Photo (P18) and locator (P242) image manifest. `kind` distinguishes. */
	images?: ObjectImage[];
	/** IAU satellite-feature parent (e.g. "Abel A" → "Abel"). Single ref. */
	parent_feature?: EntityRef;
	/** Inverse of `parent_feature` — IAU SF children of this feature. */
	satellite_features?: EntityRef[];
	/** Spatial children — features physically inside this one
	 *  (Wikidata P706 + bbox/radius derivation, minus SF children). */
	contains?: EntityRef[];
	wikidata?: {
		length?: QuantityWithUnit;
		width?: QuantityWithUnit;
		height?: QuantityWithUnit;
		area?: QuantityWithUnit;
		elevation?: QuantityWithUnit;
		vertical_depth?: QuantityWithUnit;
		/** Forward-compat: writer schema may surface currencies as a unit; not
		 *  expected for features but keeps the type aligned with objects. */
		[other: string]: QuantityWithUnit | CurrencyQuantity | number | string | undefined;
	};
}

/** Per-language overlay. Mirrors `_build_detail_localized` on the writer. */
export interface FeatureLocalizedData {
	description?: string;
	aliases?: string[];
	instance_of?: EntityRef[];
	named_after?: EntityRef[];
	/** Spatial parents — features/bodies this one is inside (Wikidata P706 +
	 *  P361 + bbox/radius derivation, minus its IAU SF parent). */
	inside_of?: EntityRef[];
	/** IAU quadrangle this feature sits in. ``wikipedia`` is the sitelink
	 *  for the loaded language when its QID is in
	 *  ``constants/quadrangle_refs.py`` and the entity has been downloaded. */
	quadrangle?: EntityRef;
	wikipedia?: {
		extract?: string;
		description?: string;
		url?: string;
	};
}

export interface FeatureDetailData {
	global: FeatureGlobalData | null;
	localized: FeatureLocalizedData | null;
}

/** Bucket id = key under which the writer stored the per-feature entry. */
export function featureBucketKey(bodyId: string, featureId: number): string {
	return `${bodyId}:${featureId}`;
}

const bundleCache = new Map<string, Promise<Record<string, unknown>>>();

async function fetchBundle<T>(url: string): Promise<Record<string, T>> {
	let p = bundleCache.get(url);
	if (!p) {
		p = (async () => {
			const res = await fetch(url);
			if (!res.ok) {
				if (res.status === 404) return {};
				throw new Error(`fetchBundle: ${url} returned ${res.status} ${res.statusText}`);
			}
			const ds = new DecompressionStream('gzip');
			return (await new Response(res.body!.pipeThrough(ds)).json()) as Record<string, unknown>;
		})();
		bundleCache.set(url, p);
	}
	return p as Promise<Record<string, T>>;
}

/**
 * Fetch the global + localized detail bundles for one IAU feature.
 *
 * Mirrors `fetchObjectDetail` — looks up bucket counts in
 * `metadata.feature_bundles`, hashes the `${bodyId}:${featureId}` key, and
 * pulls the gzipped JSON bundles in parallel. Returns `{global: null,
 * localized: null}` when the metadata predates feature bundles or no
 * bucket holds this feature.
 */
export async function fetchFeatureDetail(
	bodyId: string,
	featureId: number,
	lang = getLocale()
): Promise<FeatureDetailData> {
	const meta = await fetchMetadata();
	const bundles = meta.feature_bundles;
	if (!bundles) return { global: null, localized: null };

	const key = featureBucketKey(bodyId, featureId);
	const nGlobal = bundles.global;
	const nLocalized = bundles[lang] ?? 0;

	const [globalBucket, localizedBucket] = await Promise.all([
		nGlobal ? hashBucket(key, nGlobal) : Promise.resolve(-1),
		nLocalized ? hashBucket(key, nLocalized) : Promise.resolve(-1)
	]);

	const globalPromise: Promise<FeatureGlobalData | undefined> =
		globalBucket >= 0
			? fetchBundle<FeatureGlobalData>(
					versionedUrl(
						`/v1/nomenclature/details/__global__/${globalBucket}.json.gz`,
						'nomenclature'
					)
				).then((b) => b[key])
			: Promise.resolve(undefined);

	const localizedPromise: Promise<FeatureLocalizedData | undefined> =
		localizedBucket >= 0
			? fetchBundle<FeatureLocalizedData>(
					versionedUrl(
						`/v1/nomenclature/details/${lang}/${localizedBucket}.json.gz`,
						'nomenclature'
					)
				).then((b) => b[key])
			: Promise.resolve(undefined);

	const [global, localized] = await Promise.all([globalPromise, localizedPromise]);
	return { global: global ?? null, localized: localized ?? null };
}
