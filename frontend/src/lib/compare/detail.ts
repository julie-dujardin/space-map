/**
 * The drawer's focus target for an object in the comparison.
 *
 * The compare page draws no scene, so there is no streamed chunk to take a
 * body from: it is built from the object's own bundle instead. The result is a
 * page to read, never a thing to place — nothing on this page puts a camera on
 * it, so the position stands at the origin and says so. A rocket has no page
 * of its own and opens on its family's group instead.
 */

import { bodyDataFromGlobal, unplacedBodyDataFromGlobal } from '$lib/fetch/objects/global-body';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import type { Focusable } from '$lib/state/focusable';
import { rocketBySlug } from './rockets';

/** The drawer's body and group variants — the shapes this page focuses. */
export type CompareFocus = Extract<Focusable, { kind: 'body' | 'group' }>;

export async function compareFocusable(id: string): Promise<CompareFocus | null> {
	const group = rocketBySlug(id)?.group;
	if (group) return { kind: 'group', slug: group };
	const detail = await fetchObjectDetail(id).catch(() => null);
	if (!detail?.global) return null;
	const data = bodyDataFromGlobal(id, detail) ?? unplacedBodyDataFromGlobal(id, detail);
	if (!data) return null;
	return { kind: 'body', body: { data, position: [0, 0, 0], positionUnknown: true } };
}
