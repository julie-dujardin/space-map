/**
 * Shared small-body group predicate: does one body satisfy the active
 * /g/<slug> filter? Used by the render-time hide (VisibilityController) and by
 * the sticky-focus membership test (ContextManager), which must agree — a body
 * that renders as a member has to read as one when it is clicked.
 */

import { ObjectType, sbdbOrbitClass } from '$lib/types/objects';
import { isTopLevelParent, type BodyIndex } from '$lib/scene/state/bodies.svelte';
import { smallBodyCategory, type SmallBodyFilter } from '$lib/fetch/groups/registry';

export const SMALL_BODY_ZONE_PREFIX = 'small_bodies/';

/** SBDB orbit-class name for a small body: its zone suffix, or — for un-zoned
 *  dwarf planets — derived from heliocentric (a, e) since AMO/MCA/APO overlap
 *  the main belt's `a` band. Walks one level up for Pluto, whose `data.a` is
 *  around its barycenter. Null when the class can't be resolved. */
export function resolveSmallBodyClass(bodies: BodyIndex, id: string): string | null {
	const zone = bodies.findAsteroidZone(id);
	if (zone && zone.startsWith(SMALL_BODY_ZONE_PREFIX)) {
		return zone.slice(SMALL_BODY_ZONE_PREFIX.length);
	}
	const body = bodies.bodiesById.get(id);
	if (body?.data.objectType !== ObjectType.DWARF_PLANET) return null;
	let a = body.data.a;
	let e = body.data.e;
	if (!isTopLevelParent(body.data.parentId)) {
		const parent = bodies.bodiesById.get(body.data.parentId);
		if (parent?.data.a) {
			a = parent.data.a;
			e = parent.data.e;
		}
	}
	return sbdbOrbitClass(a, e);
}

/** True when `id` satisfies an active filter; unresolved bodies never match,
 *  so off-class promoted bodies stay hidden. The no-filter answer is the
 *  caller's — the visibility path shows everything, the membership path claims
 *  nothing — so it isn't decided here. Asteroid moons are matched through their
 *  parent id by the caller, not through this predicate. */
export function matchesSmallBodyFilter(
	bodies: BodyIndex,
	id: string,
	filter: SmallBodyFilter
): boolean {
	if (filter.kind === 'class' || filter.kind === 'category') {
		const className = resolveSmallBodyClass(bodies, id);
		if (className === null) return false;
		return filter.kind === 'class'
			? className === filter.className
			: smallBodyCategory(className) === filter.category;
	}
	// Promoted small bodies live in `asteroidBodiesByZone`, not `bodiesById` —
	// go through getBody so flags resolve.
	const body = bodies.getBody(id);
	if (body === undefined) return false;
	return ((body.data.flags ?? 0) & filter.mask) === filter.mask;
}
