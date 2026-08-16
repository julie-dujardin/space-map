/**
 * Finding the bodies a trip is made of.
 *
 * The scene only holds what it's drawing, split across several places —
 * majors in one index, small bodies in per-zone buckets, spacecraft under
 * their parent. A trip end can be any object in the catalogue, so resolving
 * one can't go through the scene alone: what it has is used as-is, and
 * everything else is read from the global bundle, which describes every
 * object whether or not it's on screen.
 *
 * The walk goes up to the heliocentric orbit, since that's what a transfer is
 * flown between — so a moon of an asteroid pulls in the asteroid too.
 */

import type { BodyData } from '$lib/types/objects';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { bodyDataFromGlobal } from '$lib/fetch/objects/global-body';
import { isHeliocentricRoot } from './travel-body';

/** Bundle-derived rows, kept for the session: the catalogue does not change
 *  under us, and a trip re-walks the same ancestors on every swap. */
const cache = new Map<string, Promise<BodyData | null>>();

/** How many links up the chain to follow before calling it a cycle. */
const MAX_HOPS = 8;

function fromBundle(id: string): Promise<BodyData | null> {
	const hit = cache.get(id);
	if (hit) return hit;
	const pending = fetchObjectDetail(id, false)
		.then((detail) => {
			const body = bodyDataFromGlobal(id, detail);
			if (!body) console.debug(`[travel] ${id} has no orbit in its bundle — not a trip end.`);
			return body;
		})
		.catch((e) => {
			console.warn(`[travel] could not read ${id} from the catalogue:`, e);
			cache.delete(id);
			return null;
		});
	cache.set(id, pending);
	return pending;
}

/**
 * Every body the given trip ends need: each end, and the chain above it up to
 * whatever orbits the Sun.
 *
 * `resident` is asked first so a body already in the scene keeps the elements
 * being drawn. An end whose chain can't be closed is simply absent from the
 * result, which the panel reads as a trip it can't price.
 */
export async function resolveTripBodies(
	ids: readonly string[],
	resident: (id: string) => BodyData | null | undefined
): Promise<Map<string, BodyData>> {
	const out = new Map<string, BodyData>();
	await Promise.all(ids.map((id) => walk(id, resident, out)));
	return out;
}

async function walk(
	id: string,
	resident: (id: string) => BodyData | null | undefined,
	out: Map<string, BodyData>
): Promise<void> {
	let currentId = id;
	for (let hop = 0; hop < MAX_HOPS; hop++) {
		// Already walked, from this trip's other end.
		if (out.has(currentId)) return;
		const body = resident(currentId) ?? (await fromBundle(currentId));
		if (!body) {
			console.debug(`[travel] chain above ${id} stops at ${currentId} — no orbit for it.`);
			return;
		}
		out.set(currentId, body);
		if (isHeliocentricRoot(body.parentId)) return;
		currentId = body.parentId;
	}
	console.warn(`[travel] parent chain above ${id} did not reach the Sun in ${MAX_HOPS} hops.`);
}
