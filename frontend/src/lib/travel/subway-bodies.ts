/**
 * The bodies the Δv map is drawn between, as the catalogue describes them.
 *
 * The map's tree hangs off gravitational primaries, not the export's parent
 * ids: the Moon is filed under the Earth-Moon barycentre, but it is Earth's
 * well a trip climbs out of and Earth's mass the climb is priced against.
 * Barycentres are therefore skipped and every planet becomes the primary of
 * its own moons, with the Sun at the root.
 */

import type { BodyData } from '$lib/types/objects';
import { fetchObjectDetail, type ObjectDetailData } from '$lib/fetch/objects/object-data';
import { meanRadiusKm } from '$lib/fetch/objects/physical';
import { fetchSolarSystemMap } from '$lib/fetch/groups/solar-system-map';
import { loadAtmospheres } from '$lib/fetch/atmospheres';
import { loadSystemsGlobal } from '$lib/fetch/systems-global';
import { GM_SUN_KM3_S2, type TravelBody } from '$lib/math/travel';
import type { SubwayBodies, SubwayBody } from '$lib/math/travel/subway';
import { AU_KM } from '$lib/math/units';
import { BODY_COLORS, SUN_ID } from '$lib/constants';
import { resolveBodyColor } from '$lib/body-color';
import { hasGround, maxRadiusKm, synchronousRadiusKm } from './orbits';
import { resolveTripBodies } from './resolve';
import {
	heliocentricAncestor,
	hillPrimaryOf,
	isHeliocentricRoot,
	lookupIn,
	naifId,
	toTravelBody
} from './travel-body';

/** IAU mean radius of the Sun, km. Not in the catalogue as a body row, so
 *  the one figure the root needs is here. */
const SUN_RADIUS_KM = 695700;

/** Radius of the orbit in step with the body's spin, km, or undefined where no
 *  spin is on record or the body does not hold an orbit that far out. The Hill
 *  cap is the planner's own rule: without it the map draws and prices a
 *  stationary stop the planner will not offer — the Moon's lies well outside
 *  Earth's pull on it, as does Venus's. */
function syncRadiusKm(
	travel: TravelBody,
	detail: ObjectDetailData | null | undefined
): number | undefined {
	const spinDegPerDay = detail?.global?.orientation?.w1;
	if (!spinDegPerDay || !(Math.abs(spinDegPerDay) > 0)) return undefined;
	const rSync = synchronousRadiusKm(travel.mu, (24 * 360) / Math.abs(spinDegPerDay));
	return rSync < maxRadiusKm({ hillKm: travel.hillKm }) ? rSync : undefined;
}

/** The body a row is held by, as the map's tree names it. */
function primaryIdOf(row: BodyData): string | null {
	const primary = hillPrimaryOf(row);
	if (primary === null) return null;
	return primary === 'sun' ? SUN_ID : `naif-${primary}`;
}

/** NAIF 1–9 are the planetary barycentres: places, not bodies. */
function isBarycentre(id: string): boolean {
	const n = naifId(id);
	return n !== null && n >= 1 && n <= 9;
}

/**
 * The map's bodies from catalogue rows. Rows that cannot be placed on the
 * tree — a barycentre, a body with no primary, one whose orbit the kernel
 * cannot read — are left out, and a route to them is simply absent.
 */
export function subwayBodies(
	rows: ReadonlyMap<string, BodyData>,
	details: ReadonlyMap<string, ObjectDetailData | null>,
	/** Radii, km, for bodies whose bundle carries none — the minimap's. */
	radii: ReadonlyMap<string, number> = new Map()
): SubwayBodies {
	const lookup = lookupIn(rows);
	const out = new Map<string, SubwayBody>();
	// The root is a destination too — a low solar orbit is a place to price a
	// trip to, however absurd the figure. Its elements are never read: nothing
	// is transferred about a body above it.
	out.set(SUN_ID, {
		id: SUN_ID,
		mu: GM_SUN_KM3_S2,
		primaryId: null,
		orbitRadiusKm: 0,
		travel: {
			id: SUN_ID,
			mu: GM_SUN_KM3_S2,
			muEstimated: false,
			radiusKm: SUN_RADIUS_KM,
			elements: { a: 0, e: 0, i: 0, om: 0, w: 0, ma: 0, n: 0, epoch: 0 },
			hasAtmosphere: true
		},
		ground: false
	});
	for (const row of rows.values()) {
		if (isHeliocentricRoot(row.id) || isBarycentre(row.id)) continue;
		const primaryId = primaryIdOf(row);
		if (primaryId === null) continue;
		// About the Sun it is the heliocentric orbit that sets the transfer, not
		// the wobble about the barycentre the row itself describes.
		const orbit = primaryId === SUN_ID ? heliocentricAncestor(row, lookup) : row;
		if (!orbit) continue;
		const aAu = (primaryId === SUN_ID ? orbit.helioElements?.a : undefined) ?? orbit.a;
		if (!(aAu > 0)) continue;
		const global = details.get(row.id)?.global ?? null;
		// A bundle-built row only carries SBDB's diameter, which a major body has
		// none of; without a radius every burn is priced against a 1 km rock.
		const sized = Number.isFinite(row.radiusKm)
			? row
			: { ...row, radiusKm: meanRadiusKm(global) ?? radii.get(row.id) ?? NaN };
		const travel = toTravelBody(sized, lookup, global, 'own');
		if (!travel) continue;
		out.set(row.id, {
			id: row.id,
			mu: travel.mu,
			primaryId,
			orbitRadiusKm: aAu * AU_KM,
			travel,
			ground: hasGround(travel),
			synchronousRadiusKm: syncRadiusKm(travel, details.get(row.id))
		});
	}
	return out;
}

export interface SubwayCatalogue {
	bodies: SubwayBodies;
	names: ReadonlyMap<string, string>;
	/** The tint the map draws each body in. */
	colors: ReadonlyMap<string, string>;
}

/**
 * Destinations shown alongside the minimap's Sun, planets and large moons
 * before anyone picks: two dwarf planets and one distant object worth the
 * comparison, and the small moons of the two smaller primaries. A judgement
 * about this page, not a fact about the bodies, so a list rather than a rule.
 */
const DEFAULT_EXTRA_TARGETS: readonly string[] = [
	'naif-2000001', // Ceres
	'naif-999', // Pluto
	'naif-901', // Charon
	'spkid-20090377', // Sedna
	'naif-401', // Phobos
	'naif-402' // Deimos
];

/** The destinations shown before anyone picks. */
export async function defaultSubwayTargets(): Promise<string[]> {
	const map = await fetchSolarSystemMap();
	const ids = map.objects
		.filter(
			(object) => object.kind === 'star' || object.kind === 'planet' || object.kind === 'moon'
		)
		.map((object) => object.id);
	return [...ids, ...DEFAULT_EXTRA_TARGETS.filter((id) => !ids.includes(id))];
}

/**
 * Catalogues already assembled this session, keyed by the id set asked for.
 *
 * Assembling one reads the detail bundle of every body on the map — 67 buckets
 * for the default set, against a bundle LRU that holds 24 — so the LRU cannot
 * hold the working set and every pass re-downloads and re-parses all of it,
 * about 0.7 s. Raising that cap is not the trade: a parsed bucket is ~2 MB,
 * while a catalogue is a few bodies' worth of derived figures.
 */
const catalogues = new Map<string, Promise<SubwayCatalogue>>();

/** Distinct catalogues kept: the page holds one, and an origin or a target
 *  tried and gone back on holds another. */
const MAX_CATALOGUES = 8;

/**
 * Every body the map needs to route between `ids`: the bodies themselves, the
 * chain above each up to the Sun, and the planet inside any barycentre on the
 * way, which the chain walk does not visit but the tree hangs a moon from.
 *
 * Memoized per id set, so returning to the map redraws it rather than rebuilding
 * it. The export is fixed for the life of the page, so nothing goes stale.
 */
export function fetchSubwayCatalogue(ids: readonly string[]): Promise<SubwayCatalogue> {
	const key = [...new Set(ids)].sort().join(',');
	const held = catalogues.get(key);
	if (held) {
		// Refresh recency (Map iterates in insertion order).
		catalogues.delete(key);
		catalogues.set(key, held);
		return held;
	}
	const pending = buildSubwayCatalogue(ids);
	catalogues.set(key, pending);
	// Evict on rejection so one failed pass does not answer for the session.
	pending.catch(() => {
		if (catalogues.get(key) === pending) catalogues.delete(key);
	});
	for (const oldest of catalogues.keys()) {
		if (catalogues.size <= MAX_CATALOGUES) break;
		catalogues.delete(oldest);
	}
	return pending;
}

async function buildSubwayCatalogue(ids: readonly string[]): Promise<SubwayCatalogue> {
	await Promise.all([loadSystemsGlobal(), loadAtmospheres()]);
	const rows = new Map<string, BodyData>();
	let pending = [...new Set(ids)];
	// Each pass can surface a primary the last one did not have; a chain is a
	// few links long, so this settles in two or three.
	while (pending.length > 0) {
		const found = await resolveTripBodies(pending, (id) => rows.get(id));
		for (const [id, row] of found) rows.set(id, row);
		const missing = new Set<string>();
		for (const row of found.values()) {
			const primaryId = primaryIdOf(row);
			if (primaryId && !rows.has(primaryId)) missing.add(primaryId);
		}
		pending = [...missing];
	}
	// The Sun has no row — the chain walk stops under it — but it has a name.
	const details = new Map<string, ObjectDetailData | null>();
	await Promise.all(
		[...rows.keys(), SUN_ID].map(async (id) => {
			details.set(id, await fetchObjectDetail(id).catch(() => null));
		})
	);
	const names = new Map<string, string>();
	const colors = new Map<string, string>([[SUN_ID, BODY_COLORS[SUN_ID]]]);
	for (const [id, detail] of details) {
		const row = rows.get(id);
		names.set(id, detail?.localized?.name ?? detail?.global?.name ?? row?.name ?? id);
		if (row) colors.set(id, resolveBodyColor(row));
	}
	// The minimap knows sizes the bundles do not, for the far dwarfs.
	const radii = new Map(
		(await fetchSolarSystemMap()).objects.map((object) => [object.id, object.diameter_km / 2])
	);
	return { bodies: subwayBodies(rows, details, radii), names, colors };
}

/**
 * `ids` ordered by distance from the Sun: by the heliocentric body each hangs
 * under, then by their own orbit, so a system's moons stay with it. Ids the
 * map does not hold keep their place at the end.
 */
export function sortByDistance(bodies: SubwayBodies, ids: readonly string[]): string[] {
	const rank = (id: string): [number, number] | null => {
		const body = bodies.get(id);
		if (!body) return null;
		let top = body;
		while (top.primaryId && top.primaryId !== SUN_ID) {
			const up = bodies.get(top.primaryId);
			if (!up) break;
			top = up;
		}
		return [top.orbitRadiusKm, top === body ? 0 : body.orbitRadiusKm];
	};
	return [...ids]
		.map((id, i) => ({ id, i, rank: rank(id) }))
		.sort((a, b) => {
			if (!a.rank || !b.rank) return (a.rank ? 0 : 1) - (b.rank ? 0 : 1) || a.i - b.i;
			return a.rank[0] - b.rank[0] || a.rank[1] - b.rank[1] || a.i - b.i;
		})
		.map((x) => x.id);
}

/** A satellite system as the target drawer groups it: the body under the Sun
 *  and, after it, whatever of its moons are on the list. */
export interface SubwaySystem {
	id: string;
	members: string[];
}

/**
 * `ids` grouped by the heliocentric body each hangs under, systems in
 * distance order and moons by their own orbit within one. A body the map does
 * not hold makes a system of its own at the end.
 */
export function groupBySystem(bodies: SubwayBodies, ids: readonly string[]): SubwaySystem[] {
	const topOf = (id: string): string => {
		let body = bodies.get(id);
		while (body?.primaryId && body.primaryId !== SUN_ID) body = bodies.get(body.primaryId);
		return body?.id ?? id;
	};
	const members = new Map<string, string[]>();
	for (const id of sortByDistance(bodies, ids)) {
		const top = topOf(id);
		members.set(top, [...(members.get(top) ?? []), id]);
	}
	return [...members].map(([id, list]) => ({ id, members: list }));
}
