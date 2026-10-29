/**
 * The families that a star's or a planet's page links to, from the family
 * trees of `metadata.json`.
 */

import { PLANET_FAMILY_SLUG_PREFIX, STAR_FAMILY_SLUG_PREFIX } from '$lib/fetch/groups/registry';
import type { ExtrasolarFamily } from './files';

export type FamilyType = 'star_family' | 'planet_family';

const SLUG_PREFIX: Record<FamilyType, string> = {
	star_family: STAR_FAMILY_SLUG_PREFIX,
	planet_family: PLANET_FAMILY_SLUG_PREFIX
};

export interface FamilyLink {
	type: FamilyType;
	/** The family's page, `star-<family>` or `planet-<family>`. */
	slug: string;
	/** True when only an estimate puts the object in it. */
	estimated: boolean;
}

/** The families whose bits the star mask `mask` sets. */
export function familiesOf(mask: bigint, families: readonly ExtrasolarFamily[]): string[] {
	return families.filter((_, n) => (mask >> BigInt(n)) & 1n).map((family) => family.slug);
}

/**
 * The most specific of an object's families. First the published ones that
 * contain no other published one: a published family keeps its tile when
 * only an estimate is more specific. Then the estimated ones that contain
 * none of the object's families. Fewer members first within each. The lists
 * hold every parent of their families. Empty without the tree.
 */
export function familyLinks(
	type: FamilyType,
	published: readonly string[],
	estimated: readonly string[],
	families: readonly ExtrasolarFamily[]
): FamilyLink[] {
	if (families.some((family) => !family.parents)) return [];
	const bySlug = new Map(families.map((family) => [family.slug, family]));
	const parentsOf = (slugs: readonly string[]) =>
		new Set(slugs.flatMap((slug) => bySlug.get(slug)?.parents ?? []));
	const members = (slug: string) => {
		const family = bySlug.get(slug);
		return family ? family.published + family.estimated : 0;
	};
	const pick = (slugs: readonly string[], contained: Set<string>, isEstimate: boolean) =>
		slugs
			.filter((slug) => !contained.has(slug))
			.sort((a, b) => members(a) - members(b) || a.localeCompare(b))
			.map((slug) => ({ type, slug: `${SLUG_PREFIX[type]}${slug}`, estimated: isEstimate }));
	return [
		...pick(published, parentsOf(published), false),
		...pick(estimated, parentsOf([...published, ...estimated]), true)
	];
}
