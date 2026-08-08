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
export function isHeliocentricRoot(objectId: string): boolean {
	const id = naifId(objectId);
	return id === SUN_ID || id === SSB_ID;
}

/**
 * How the walk finds a parent. A function rather than a map because the bodies
 * a trip needs come from several places — the scene's own index, and the
 * catalogue for anything it never loaded.
 */
export type BodyLookup = (id: string) => BodyData | null | undefined;

/** The lookup a plain map makes. */
export function lookupIn(bodiesById: ReadonlyMap<string, BodyData>): BodyLookup {
	return (id) => bodiesById.get(id);
}

/** How many links up the chain to follow. Real chains are three or four; the
 *  cap only guards against a cycle in malformed data. */
const MAX_HOPS = 8;

/**
 * The ancestor whose orbit is about the Sun.
 *
 * Earth resolves to the Earth-Moon barycentre, Europa to the Jupiter
 * barycentre, an asteroid to itself. Returns null when the chain cannot be
 * walked — a body whose parent the lookup cannot produce has no heliocentric
 * orbit we can name.
 */
export function heliocentricAncestor(body: BodyData, lookup: BodyLookup): BodyData | null {
	const chain = ancestry(body, lookup);
	return chain ? chain[chain.length - 1] : null;
}

/**
 * Levels that are a reading at the surface, whatever shape that surface is
 * given. Mirrors `_DATUM_OF_LEVEL` in the exporter's atmosphere module — Earth
 * quotes sea level and Mars the areoid, and both are the ground.
 *
 * `one_bar` and `cloud_top` are levels inside an envelope with no surface under
 * them, so they are deliberately absent: the giants price as airless, which
 * overcharges their capture but never invents a place to land.
 */
const SURFACE_LEVELS: ReadonlySet<string> = new Set(['surface', 'sea_level', 'areoid']);

/** Surface pressure in bar, or undefined when the body has no atmosphere. */
function surfacePressureBar(detail: GlobalObjectData | null): number | undefined {
	const pressure = detail?.atmosphere?.pressure;
	if (!pressure) return undefined;
	if (!SURFACE_LEVELS.has(pressure.level)) {
		console.debug(
			`[travel] ${detail?.id}: pressure quoted at "${pressure.level}", not a surface — pricing it airless.`
		);
		return undefined;
	}
	if (!Number.isFinite(pressure.pa) || pressure.pa <= 0) return undefined;
	return pressure.pa / 1e5;
}

/**
 * Which orbit describes the body in the frame its trip is solved in: the one
 * about the Sun, or its own about whatever it goes round. A trip across the
 * solar system needs the first; a trip inside one system needs the second.
 */
export type OrbitChoice = 'heliocentric' | 'own';

/**
 * Build the kernel's view of `body`.
 *
 * `detail` is optional — without it the body is treated as airless, which only
 * changes whether the arrival gets an aerocapture discount.
 *
 * Returns null when the body has no orbit of the requested kind.
 */
export function toTravelBody(
	body: BodyData,
	lookup: BodyLookup,
	detail: GlobalObjectData | null = null,
	orbit: OrbitChoice = 'heliocentric'
): TravelBody | null {
	const ancestor = orbit === 'own' ? body : heliocentricAncestor(body, lookup);
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
 * What kind of transfer a pair of bodies needs, or why it cannot have one.
 *
 * Two bodies in different systems are connected by an arc about the Sun. Two in
 * the same one are not: Earth to its own Moon shares a heliocentric orbit, so
 * there is no arc between them there, and the transfer belongs about the body
 * they both go round instead. That case only works when one end *is* that body —
 * moon to sibling moon would need a leg about a primary that is neither end, and
 * the kernel has no departure to price for it.
 */
export type TransferPlan =
	| { kind: 'heliocentric' }
	| { kind: 'system'; primary: 'origin' | 'target' }
	| { kind: 'blocked'; reason: 'unknown-orbit' | 'same-primary' };

/**
 * The body at the centre of a planetary barycentre, by the NAIF numbering the
 * export uses throughout: barycentre `naif-N` holds planet `naif-N99`. Null for
 * anything that is not one of the nine.
 */
function primaryBodyOf(barycentreId: string): string | null {
	const id = naifId(barycentreId);
	if (id === null || id < 1 || id > 9) return null;
	return `naif-${id}99`;
}

/** The body and every ancestor up to its heliocentric orbit, nearest first. */
function ancestry(body: BodyData, lookup: BodyLookup): BodyData[] | null {
	const chain: BodyData[] = [];
	let current = body;
	for (let hop = 0; hop < MAX_HOPS; hop++) {
		chain.push(current);
		if (isHeliocentricRoot(current.parentId)) return chain;
		const parent = lookup(current.parentId);
		if (!parent) return null;
		current = parent;
	}
	return null;
}

/** Bodies already reported. The search exclusions ask about every body in the
 *  scene on every render, and the answer does not change between them. */
const reportedUnwalkable = new Set<string>();

function reportUnwalkableChain(id: string): void {
	if (reportedUnwalkable.has(id)) return;
	reportedUnwalkable.add(id);
	console.debug(`[travel] no heliocentric ancestor for ${id}`);
}

export function transferPlan(origin: BodyData, target: BodyData, lookup: BodyLookup): TransferPlan {
	const from = ancestry(origin, lookup);
	const to = ancestry(target, lookup);
	if (!from || !to) {
		reportUnwalkableChain((from ? target : origin).id);
		return { kind: 'blocked', reason: 'unknown-orbit' };
	}
	if (from[from.length - 1].id !== to[to.length - 1].id) return { kind: 'heliocentric' };

	// One system. The transfer is about whichever end the other one orbits —
	// directly, as a satellite of it, or through the barycentre they share.
	const shared = new Set(to.map((b) => b.id));
	const meeting = from.find((b) => shared.has(b.id));
	if (!meeting) return { kind: 'blocked', reason: 'same-primary' };
	const centre =
		meeting.id === origin.id || meeting.id === target.id ? meeting.id : primaryBodyOf(meeting.id);
	if (centre === origin.id) return { kind: 'system', primary: 'origin' };
	if (centre === target.id) return { kind: 'system', primary: 'target' };
	return { kind: 'blocked', reason: 'same-primary' };
}
