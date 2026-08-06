/** Adapt feature and group detail bundles into the shared ObjectDetailData
 *  shape, so the drawer's header/description/links sections consume one type
 *  regardless of what's focused. */

import type { ObjectDetailData } from '$lib/fetch/objects/object-data';
import type { FeatureDetailData } from '$lib/fetch/nomenclature/details';
import type { GroupDetailData } from '$lib/fetch/groups/details';
import { categoryLabel, CATEGORY_SLUG_PREFIX } from '$lib/fetch/groups/registry';
import { groupSlugLabel } from '$lib/state/focusable';

export function featureDetailToObjectData(
	detail: FeatureDetailData,
	feature: { featureId: number; name: string }
): ObjectDetailData {
	return {
		global: {
			id: `feature-${feature.featureId}`,
			type: 'feature',
			name: feature.name,
			images: detail.global?.images,
			cross_refs: detail.global?.wikidata_qid
				? { wikidata_qid: detail.global.wikidata_qid }
				: undefined
		},
		localized: detail.localized
			? {
					description: detail.localized.description,
					aliases: detail.localized.aliases,
					instance_of: detail.localized.instance_of,
					named_after: detail.localized.named_after,
					wikipedia: detail.localized.wikipedia,
					image_titles: detail.localized.image_titles
				}
			: null
	};
}

export function groupDetailToObjectData(detail: GroupDetailData, slug: string): ObjectDetailData {
	const websites = [detail.global?.website, detail.global?.url].filter((u): u is string => !!u);
	// Categories display an i18n label, not the English bundle name.
	const name = slug.startsWith(CATEGORY_SLUG_PREFIX)
		? categoryLabel(slug)
		: (detail.localized?.name ?? groupSlugLabel(slug));
	return {
		global: {
			id: `group-${slug}`,
			type: 'group',
			name,
			images: detail.global?.images,
			cross_refs: detail.global?.wikidata_qid
				? { wikidata_qid: detail.global.wikidata_qid }
				: undefined,
			wikidata: websites.length > 0 ? { website: websites } : undefined
		},
		localized: detail.localized
			? { name, description: detail.localized.description, wikipedia: detail.localized.wikipedia }
			: null
	};
}
