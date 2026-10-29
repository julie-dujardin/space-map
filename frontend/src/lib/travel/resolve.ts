/**
 * Finding the bodies a trip is made of.
 *
 * A trip end can be any object of the catalogue, and the scene holds only what
 * it draws. A body of the solar system that the scene holds is used as it is.
 * Any other body comes from its global bundle. The walk goes up to the orbit
 * about the Sun, so a moon of an asteroid also gives the asteroid.
 *
 * An end outside the solar system has no bundle. It comes from the extrasolar
 * export (see `extrasolar-end.ts`).
 */

import type { BodyData } from '$lib/types/objects';
import { isExtrasolarObjectId } from '$lib/fetch/extrasolar/ids';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { bodyDataFromGlobal } from '$lib/fetch/objects/global-body';
import type { ExtrasolarEnd } from './extrasolar-end';
import { isHeliocentricRoot } from './travel-body';

export interface TripBodies {
	/** Each end and the chain above it up to the Sun. An end outside the solar
	 *  system is its own row, by the id it was asked by. */
	bodies: Map<string, BodyData>;
	/** The ends outside the solar system, by the id they were asked by. */
	extrasolar: Map<string, ExtrasolarEnd>;
}

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
): Promise<TripBodies> {
	const bodies = new Map<string, BodyData>();
	const extrasolar = new Map<string, ExtrasolarEnd>();
	// The Δv map also walks trips and never has an end outside the solar system,
	// so its page does not load this module.
	const outside = ids.some(isExtrasolarObjectId) ? await import('./extrasolar-end') : null;
	await Promise.all(
		ids.map(async (id) => {
			if (!outside || !isExtrasolarObjectId(id)) return walk(id, resident, bodies);
			const end = await outside.resolveExtrasolarEnd(id);
			if (!end) return;
			bodies.set(id, end.body);
			extrasolar.set(id, end);
		})
	);
	return { bodies, extrasolar };
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
