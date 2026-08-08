/**
 * Turning what the app already knows about a body into what the trajectory
 * kernel needs.
 *
 * The one subtlety is which orbit to hand over. A transfer is between two
 * *heliocentric* orbits, but Earth's own elements describe its motion about the
 * Earth-Moon barycentre, not about the Sun. So the elements come from the
 * body's heliocentric ancestor while the mass, radius and atmosphere — every
 * quantity the departure and arrival burns are priced against — come from the
 * body itself.
 */

import type { BodyData } from '$lib/types/objects';
import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
import { getGmKm3s2 } from '$lib/fetch/systems-global';
import { estimateMu, type TravelBody } from '$lib/math/travel';

/** NAIF ids at or below this are the Sun and the planetary barycentres. */
const SUN_ID = 10;
const SSB_ID = 0;

/** Numeric part of a `naif-<n>` id; null for any other prefix. */
export function naifId(objectId: string): number | null {
	if (!objectId.startsWith('naif-')) return null;
	const value = Number.parseInt(objectId.slice('naif-'.length), 10);
	return Number.isFinite(value) ? value : null;
}

/** True for the Sun or the solar-system barycentre — the roots of the walk. */
function isHeliocentricRoot(objectId: string): boolean {
	const id = naifId(objectId);
	return id === SUN_ID || id === SSB_ID;
}

/**
 * The ancestor whose orbit is about the Sun.
 *
 * Earth resolves to the Earth-Moon barycentre, Europa to the Jupiter
 * barycentre, an asteroid to itself. Returns null when the chain cannot be
 * walked — a body whose parent is missing from the loaded set has no
 * heliocentric orbit we can name.
 */
export function heliocentricAncestor(
	body: BodyData,
	bodiesById: Map<string, BodyData>
): BodyData | null {
	let current: BodyData = body;
	// The chain is a handful of links; the cap only guards against a cycle in
	// malformed data.
	for (let hop = 0; hop < 8; hop++) {
		if (isHeliocentricRoot(current.parentId)) return current;
		const parent = bodiesById.get(current.parentId);
		if (!parent) return null;
		current = parent;
	}
	return null;
}

/** Surface pressure in bar, or undefined when the body has no atmosphere. */
function surfacePressureBar(detail: GlobalObjectData | null): number | undefined {
	const pressure = detail?.atmosphere?.pressure;
	if (!pressure || pressure.level !== 'surface') return undefined;
	if (!Number.isFinite(pressure.pa) || pressure.pa <= 0) return undefined;
	return pressure.pa / 1e5;
}

/**
 * Build the kernel's view of `body`.
 *
 * `detail` is optional — without it the body is treated as airless, which only
 * changes whether the arrival gets an aerocapture discount.
 *
 * Returns null when the body has no heliocentric orbit to transfer along.
 */
export function toTravelBody(
	body: BodyData,
	bodiesById: Map<string, BodyData>,
	detail: GlobalObjectData | null = null
): TravelBody | null {
	const ancestor = heliocentricAncestor(body, bodiesById);
	if (!ancestor) return null;

	const radiusKm = Number.isFinite(body.radiusKm) && body.radiusKm > 0 ? body.radiusKm : 1;
	const id = naifId(body.id);
	const measuredMu = id === null ? undefined : getGmKm3s2(id);

	return {
		id: body.id,
		// Most of the catalogue has no measured mass; an assumed density is close
		// enough that capture and landing stay in the right order of magnitude.
		mu: measuredMu && measuredMu > 0 ? measuredMu : estimateMu(radiusKm),
		muEstimated: !(measuredMu && measuredMu > 0),
		radiusKm,
		elements: {
			a: ancestor.a,
			e: ancestor.e,
			i: ancestor.i,
			om: ancestor.om,
			w: ancestor.w,
			ma: ancestor.ma,
			n: ancestor.n,
			epoch: ancestor.epoch,
			omDot: ancestor.omDot,
			wDot: ancestor.wDot,
			equatorial: ancestor.equatorial
		},
		surfacePressureBar: surfacePressureBar(detail),
		parentId: body.parentId
	};
}

/**
 * Why these two bodies cannot be connected by a single heliocentric transfer,
 * or null when they can.
 *
 * Sharing a heliocentric ancestor is the real blocker: Earth to its own Moon is
 * one orbit to itself, which has no transfer arc at all. That trip needs a leg
 * about the shared primary, which the kernel does not yet solve.
 */
export function sameSystemBlock(
	origin: BodyData,
	target: BodyData,
	bodiesById: Map<string, BodyData>
): 'unknown-orbit' | 'same-primary' | null {
	const a = heliocentricAncestor(origin, bodiesById);
	const b = heliocentricAncestor(target, bodiesById);
	if (!a || !b) return 'unknown-orbit';
	if (a.id === b.id) return 'same-primary';
	return null;
}
