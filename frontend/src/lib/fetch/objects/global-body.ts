/**
 * A body row built from an object's global JSON rather than from a binary
 * chunk. Chunks only cover what the scene is streaming; the global bundle
 * describes every object, so it stands in for the render placeholder before a
 * chunk lands, and for a body the scene never loads at all.
 */

import { ObjectType, type BodyData } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { buildSatrec, type SGP4Inputs } from '$lib/math/orbit/sgp4';
import { J2000_JD } from '$lib/time/jd';
import { canBePlaced } from '$lib/fetch/coverage';
import { AU_KM } from '$lib/math/units';
import type { ObjectDetailData } from './object-data';

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
	spacetrack: OrbitalSource.SPACETRACK,
	spice: OrbitalSource.SPICE,
	sbdb_moons: OrbitalSource.SBDB_MOON,
	astersat: OrbitalSource.ASTERSAT
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
 * The body `detail` describes, built from the elements of its bundle. Null
 * when the map cannot place the object (no `coverage`: a docked module has
 * elements and is in no position file), and when the bundle has no full set
 * of elements: the Sun, a barycentre root, and anything the export places
 * from a position file only.
 */
export function bodyDataFromGlobal(id: string, detail: ObjectDetailData): BodyData | null {
	const global = detail.global;
	const orbit = global?.orbit;
	if (!global || !orbit || !canBePlaced(global)) return null;
	const isParabolic = orbit.q != null && orbit.tp != null;
	if (
		!isParabolic &&
		(orbit.epoch_jd == null || orbit.a == null || orbit.ma == null || orbit.n == null)
	) {
		return null;
	}

	// Planet scale means CelesTrak TLE data: kilometres and Earth-equatorial
	// angles, where everything else is AU about the ecliptic.
	const isPlanetScale = orbit.scale === 'planet';

	const noradCatId = global.cross_refs?.norad_cat_id;
	const omm: SGP4Inputs | undefined =
		isPlanetScale &&
		orbit.bstar != null &&
		orbit.mean_motion_dot != null &&
		orbit.mean_motion_ddot != null &&
		orbit.n != null &&
		noradCatId != null
			? {
					noradCatId,
					epochJd: orbit.epoch_jd,
					meanMotion: orbit.n,
					eccentricity: orbit.e,
					inclination: orbit.i,
					raOfAscNode: orbit.om,
					argOfPericenter: orbit.w,
					meanAnomaly: orbit.ma ?? 0,
					bstar: orbit.bstar,
					meanMotionDot: orbit.mean_motion_dot,
					meanMotionDdot: orbit.mean_motion_ddot,
					elementSetNo: orbit.element_set_no ?? 0,
					revAtEpoch: orbit.rev_at_epoch ?? 0
				}
			: undefined;
	const satrec = omm ? (buildSatrec(omm, global.name ?? undefined) ?? undefined) : undefined;
	// The row from a position file carries the launch or discovery gate. A
	// body built from the bundle takes it from the start of its coverage.
	const coverageStart = global.coverage?.windows[0]?.[0];

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
		validityStart: omm ? orbit.epoch_jd - SGP4_VALIDITY_SLACK_DAYS : -Infinity,
		validityEnd: omm ? orbit.epoch_jd + SGP4_VALIDITY_SLACK_DAYS : Infinity,
		orbitalSource: parseOrbitalSource(orbit.source),
		...(coverageStart != null ? { visibleFromDays: coverageStart - J2000_JD } : {}),
		...(isParabolic ? { q: orbit.q, tp: orbit.tp } : {}),
		...(omm ? { omm } : {}),
		...(satrec ? { satrec } : {})
	};
}

/**
 * A stand-in row for an object the scene has no elements for. It has a page,
 * so it can take the focus, and it has no place. A row from a position file
 * replaces its data.
 */
export function pageOnlyBodyData(id: string, detail: ObjectDetailData): BodyData | null {
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
		// The body it sits at or orbits, when the catalogue names one.
		parentId: global.host_id ?? '',
		radiusKm: global.sbdb?.diameter ? global.sbdb.diameter / 2 : NaN,
		hasLocalized: detail.localized != null,
		pageOnly: true,
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
