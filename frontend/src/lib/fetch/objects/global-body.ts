/**
 * A body row built from an object's global JSON rather than from a binary
 * chunk. Chunks only cover what the scene is streaming; the global bundle
 * describes every object, so it stands in for the render placeholder before a
 * chunk lands, and for a body the scene never loads at all.
 */

import { ObjectType, type BodyData } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { buildSatrec } from '$lib/math/orbit/sgp4';
import { AU_KM } from '$lib/math/units';
import type { GlobalObjectData, ObjectDetailData } from './object-data';

/** Map a GlobalObjectData.type string (e.g. "asteroid_main_belt") to the ObjectType enum. */
function parseObjectType(typeStr: string): ObjectType {
	const key = typeStr.toUpperCase() as keyof typeof ObjectType;
	return ObjectType[key] ?? ObjectType.UNDOCUMENTED;
}

/**
 * Map a global JSON `orbit.source` string (the lowercase `OrbitalSource`
 * enum value) to the numeric ordinal — no binary header to pull it from.
 * Returns `UNKNOWN` for an unrecognized value.
 */
const ORBIT_SOURCE_BY_NAME: Record<string, OrbitalSource> = {
	horizons: OrbitalSource.HORIZONS,
	sbdb: OrbitalSource.SBDB,
	celestrak: OrbitalSource.CELESTRAK,
	spice: OrbitalSource.SPICE,
	sbdb_moons: OrbitalSource.SBDB_MOON
};
function parseOrbitalSource(name: string | undefined): OrbitalSource {
	if (!name) return OrbitalSource.UNKNOWN;
	return ORBIT_SOURCE_BY_NAME[name] ?? OrbitalSource.UNKNOWN;
}

/** SGP4 rows (Earth satellites) are only good near their epoch, so they
 *  carry a validity window the propagation gate hides them outside of, until
 *  the real chunk overwrites it. Keplerian/parabolic orbits have no cutoff. */
const SGP4_VALIDITY_SLACK_DAYS = 14;

/**
 * The body `detail` describes, or null when it has no orbit to propagate —
 * the Sun, a barycentre root, and anything whose ephemeris the export carries
 * as sampled positions rather than elements.
 */
export function bodyDataFromGlobal(id: string, detail: ObjectDetailData): BodyData | null {
	const global = detail.global;
	if (!global?.orbit) return null;

	const orbit = global.orbit;
	// Planet scale means CelesTrak TLE data: kilometres and Earth-equatorial
	// angles, where everything else is AU about the ecliptic.
	const isPlanetScale = orbit.scale === 'planet';
	const isParabolic = orbit.q != null;

	const noradCatId = global.cross_refs?.norad_cat_id;
	const hasSGP4Fields =
		orbit.bstar != null &&
		orbit.mean_motion_dot != null &&
		orbit.mean_motion_ddot != null &&
		orbit.n != null &&
		noradCatId != null;
	const satrec =
		isPlanetScale && hasSGP4Fields
			? (buildSatrec(
					{
						noradCatId,
						epochJd: orbit.epoch_jd,
						meanMotion: orbit.n!,
						eccentricity: orbit.e,
						inclination: orbit.i,
						raOfAscNode: orbit.om,
						argOfPericenter: orbit.w,
						meanAnomaly: orbit.ma ?? 0,
						bstar: orbit.bstar!,
						meanMotionDot: orbit.mean_motion_dot!,
						meanMotionDdot: orbit.mean_motion_ddot!,
						elementSetNo: orbit.element_set_no ?? 0,
						revAtEpoch: orbit.rev_at_epoch ?? 0
					},
					global.name ?? undefined
				) ?? undefined)
			: undefined;

	return {
		id,
		// Prefer the localized (Wikidata-resolved) long form so the 3D label matches
		// what the element chunk would produce via resolve_name; global.name is the
		// raw short form (e.g. CelesTrak "IRIDIUM 33 DEB") and only a last resort.
		name:
			detail.localized?.name ??
			global.name ??
			global.sbdb_primary_designation ??
			global.provisional_designation ??
			null,
		objectType: parseObjectType(global.type),
		parentId: orbit.parent_id,
		radiusKm: global.sbdb?.diameter ? global.sbdb.diameter / 2 : NaN,
		hasLocalized: detail.localized != null,
		a: isPlanetScale ? (orbit.a ?? 0) / AU_KM : (orbit.a ?? 0),
		e: orbit.e,
		i: orbit.i,
		om: orbit.om,
		w: orbit.w,
		ma: orbit.ma ?? 0,
		n: isPlanetScale ? (orbit.n ?? 0) * 360 : (orbit.n ?? 0),
		epoch: orbit.epoch_jd,
		equatorial: isPlanetScale,
		validityStart: satrec ? orbit.epoch_jd - SGP4_VALIDITY_SLACK_DAYS : -Infinity,
		validityEnd: satrec ? orbit.epoch_jd + SGP4_VALIDITY_SLACK_DAYS : Infinity,
		orbitalSource: parseOrbitalSource(orbit.source),
		...(isParabolic ? { q: orbit.q, tp: orbit.tp } : {}),
		...(satrec ? { satrec } : {})
	};
}

/**
 * A body row for an object the catalogue carries no orbit for — an asteroid
 * moon published without elements, a probe with no ephemeris. It can never be
 * placed, but it has a page, so the scene keeps it as a focusable stand-in.
 */
export function unplacedBodyDataFromGlobal(id: string, detail: ObjectDetailData): BodyData | null {
	const global = detail.global;
	if (!global) return null;
	return {
		id,
		name:
			detail.localized?.name ??
			global.name ??
			global.sbdb_primary_designation ??
			global.provisional_designation ??
			null,
		objectType: parseObjectType(global.type),
		// No parent to hang off: the position pass reads `unplaceable` and stops
		// before it ever looks one up.
		parentId: '',
		radiusKm: global.sbdb?.diameter ? global.sbdb.diameter / 2 : NaN,
		hasLocalized: detail.localized != null,
		unplaceable: true,
		a: NaN,
		e: NaN,
		i: NaN,
		om: NaN,
		w: NaN,
		ma: NaN,
		n: NaN,
		epoch: NaN,
		validityStart: -Infinity,
		validityEnd: Infinity,
		orbitalSource: OrbitalSource.UNKNOWN
	};
}

/**
 * Whether the map can put this object anywhere.
 *
 * Mirrors `Object.has_position` on the pipeline side, read off the bundle the
 * client already has: the ingest sets that flag from the same fields, and an
 * object without it ships in no position zone and no labels file.
 *
 * The `naif-` bodies and the probes ride sampled ephemerides rather than
 * elements, so their bundles say nothing about it and they are always placed.
 * What this rejects is a satellite the archive holds no elements for, a moon of
 * an asteroid published without an orbit, and — the one case wider than the
 * flag — a decayed object whose elements are gone from the current week.
 */
export function canBePlaced(id: string, global: GlobalObjectData | null): boolean {
	if (id.startsWith('naif-') || id.startsWith('probe-')) return true;
	const orbit = global?.orbit;
	if (!orbit) return false;
	if (orbit.q != null && orbit.tp != null) return true; // parabolic comet
	return orbit.epoch_jd != null && orbit.a != null && orbit.ma != null && orbit.n != null;
}
