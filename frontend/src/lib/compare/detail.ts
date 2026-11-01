/**
 * The drawer's focus target for an object in the comparison.
 *
 * The compare page draws no scene, so there is no streamed chunk to take a
 * body from: it is built from the object's own bundle instead. The result is a
 * page to read, never a thing to place — nothing on this page puts a camera on
 * it, so the position stands at the origin and says so. A rocket has no page
 * of its own and opens on its family's group instead. A star of the extrasolar
 * catalogue reads from its record.
 */

import { extrasolarIdOf, isStarObjectId } from '$lib/fetch/extrasolar/ids';
import { extrasolarLookup } from '$lib/fetch/extrasolar/lookup';
import { bodyDataFromGlobal, pageOnlyBodyData } from '$lib/fetch/objects/global-body';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { makeStarBody } from '$lib/scene/focus/star-focus';
import type { Focusable } from '$lib/state/focusable';
import { rocketBySlug } from './rockets';

/** The drawer's body and group variants — the shapes this page focuses. */
export type CompareFocus = Extract<Focusable, { kind: 'body' | 'group' | 'star' }>;

export async function compareFocusable(id: string): Promise<CompareFocus | null> {
	const group = rocketBySlug(id)?.group;
	if (group) return { kind: 'group', slug: group };
	if (isStarObjectId(id)) {
		const found = await extrasolarLookup.live(extrasolarIdOf(id) ?? id).catch(() => null);
		if (found?.kind !== 'live') return null;
		return { kind: 'star', body: makeStarBody(found.record), record: found.record };
	}
	const detail = await fetchObjectDetail(id).catch(() => null);
	if (!detail?.global) return null;
	const data = bodyDataFromGlobal(id, detail) ?? pageOnlyBodyData(id, detail);
	if (!data) return null;
	return { kind: 'body', body: { data, position: null } };
}
