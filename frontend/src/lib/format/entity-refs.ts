import type { EntityRef } from '$lib/fetch/objects/object-data';

/** Two refs name the same thing when they share a Wikipedia article, or, with
 *  no article to compare, a name. */
export function sameRef(a: EntityRef, b: EntityRef): boolean {
	return a.wikipedia && b.wikipedia ? a.wikipedia === b.wikipedia : a.name === b.name;
}

/** `refs` minus what a more specific row already shows, so "Part of" never
 *  repeats the family, mission or constellation row above it. */
export function withoutRefs(
	refs: readonly EntityRef[] | undefined,
	shown: readonly EntityRef[]
): EntityRef[] {
	return (refs ?? []).filter((r) => !shown.some((s) => sameRef(r, s)));
}
