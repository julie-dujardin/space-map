/**
 * The star families that a star's page links to, from the Metadata masks and
 * the family tree of `metadata.json`.
 */

import { STAR_FAMILY_SLUG_PREFIX } from '$lib/fetch/groups/registry';
import type { ExtrasolarFamily } from './files';

export interface StarFamilyLink {
	/** The family's page, `star-<family>`. */
	slug: string;
	/** True when only a Gaia DR3 estimate puts the star in it. */
	estimated: boolean;
}

/** The families whose bits `mask` sets. */
export function familiesOf(mask: bigint, families: readonly ExtrasolarFamily[]): string[] {
	return families.filter((_, n) => (mask >> BigInt(n)) & 1n).map((family) => family.slug);
}

/**
 * The most specific of a star's families. First the published ones that
 * contain no other published one: a catalogued family keeps its tile when
 * only an estimate is more specific. Then the estimated ones that contain
 * none of the star's families. Fewer stars first within each. The lists hold
 * every parent of their families, as the masks do. Empty without the tree.
 */
export function starFamilyLinks(
	published: readonly string[],
	estimated: readonly string[],
	families: readonly ExtrasolarFamily[]
): StarFamilyLink[] {
	if (families.some((family) => !family.parents)) return [];
	const bySlug = new Map(families.map((family) => [family.slug, family]));
	const parentsOf = (slugs: readonly string[]) =>
		new Set(slugs.flatMap((slug) => bySlug.get(slug)?.parents ?? []));
	const stars = (slug: string) => {
		const family = bySlug.get(slug);
		return family ? family.published + family.estimated : 0;
	};
	const pick = (slugs: readonly string[], contained: Set<string>, isEstimate: boolean) =>
		slugs
			.filter((slug) => !contained.has(slug))
			.sort((a, b) => stars(a) - stars(b) || a.localeCompare(b))
			.map((slug) => ({ slug: `${STAR_FAMILY_SLUG_PREFIX}${slug}`, estimated: isEstimate }));
	return [
		...pick(published, parentsOf(published), false),
		...pick(estimated, parentsOf([...published, ...estimated]), true)
	];
}
