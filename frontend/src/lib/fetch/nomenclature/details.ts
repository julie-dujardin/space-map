/**
 * Per-feature detail loader: hash-bucketed JSON bundles, mirroring the
 * objects-pipeline shape. Fetched on drawer open, not eagerly with the
 * marker positions — those only carry lean per-body marker metadata.
 * Bucket key `${bodyId}:${featureId}` must match `feature_bucket_key` in
 * `data/src/space_map_data/export/nomenclature/writer.py`.
 */

import { getLocale } from '$lib/host';
import {
	fetchBundlePair,
	FEATURE_BUNDLES,
	prefetchBundlePair,
	type BundlePair
} from '$lib/fetch/bundle-pair';
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
	// The three lists above name each feature by the global name of its page;
	// `feature_names` of the localized entry has the other languages.
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
	 *  P361 + bbox/radius derivation, minus its IAU SF parent), by the names
	 *  of their pages in this language, sorted by them. */
	inside_of?: EntityRef[];
	/** Feature id → the name in this language of a feature that the global
	 *  `parent_feature`, `satellite_features` or `contains` names, where it
	 *  differs from the global name. Read with `localizeFeatures`. */
	feature_names?: Record<string, string>;
	/** IAU quadrangle this feature sits in. ``wikipedia`` is the sitelink
	 *  for the loaded language when its QID is in
	 *  ``constants/quadrangle_refs.py`` and the entity has been downloaded. */
	quadrangle?: EntityRef;
	wikipedia?: {
		extract?: string;
		description?: string;
		url?: string;
	};
	/** Commons filename → localized picture title, for the feature's gallery. */
	image_titles?: Record<string, string>;
}

export type FeatureDetailData = BundlePair<FeatureGlobalData, FeatureLocalizedData>;

/** The features of a global list, by their names in the language of
 *  `localized`. */
export function localizeFeatures(
	refs: readonly EntityRef[],
	localized: FeatureLocalizedData | null | undefined
): EntityRef[] {
	return refs.map((ref) => {
		const name = ref.secondary_id && localized?.feature_names?.[ref.secondary_id];
		return name ? { ...ref, name } : ref;
	});
}

/** Bucket id = key under which the writer stored the per-feature entry. */
export function featureBucketKey(bodyId: string, featureId: number): string {
	return `${bodyId}:${featureId}`;
}

/** Fetch the global + localized detail bundles for one IAU feature. */
export function fetchFeatureDetail(
	bodyId: string,
	featureId: number,
	lang = getLocale()
): Promise<FeatureDetailData> {
	return fetchBundlePair<FeatureGlobalData, FeatureLocalizedData>(
		FEATURE_BUNDLES,
		featureBucketKey(bodyId, featureId),
		lang
	);
}

/** Warm a feature's detail bundle ahead of the drawer that will read it. */
export function prefetchFeatureDetail(bodyId: string, featureId: number): Promise<void> {
	return prefetchBundlePair(FEATURE_BUNDLES, featureBucketKey(bodyId, featureId));
}
