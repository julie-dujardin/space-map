/**
 * A body row built from an object's global JSON rather than from a binary
 * chunk.
 *
 * The chunks are where elements normally come from, but they only cover what
 * the scene is currently streaming. The global bundle describes every object in
 * the catalogue, so it is what stands in when the chunk has not landed (the
 * render placeholder) and what answers for a body the scene never loads at all
 * (a trip end far outside the view).
 */

import { ObjectType, type BodyData } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { buildSatrec } from '$lib/math/orbit/sgp4';
import { AU_KM } from '$lib/math/units';
import type { ObjectDetailData } from './object-data';

/** Map a GlobalObjectData.type string (e.g. "asteroid_main_belt") to the ObjectType enum. */
function parseObjectType(typeStr: string): ObjectType {
	const key = typeStr.toUpperCase() as keyof typeof ObjectType;
	return ObjectType[key] ?? ObjectType.UNDOCUMENTED;
}

/**
 * Map a global JSON `orbit.source` string (the lowercase `OrbitalSource` enum
 * value) back to the numeric ordinal — a body described by its JSON has no
 * binary header to pull from, so we parse the string. Returns `UNKNOWN` if the
 * server sent a value the frontend doesn't know.
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

/**
 * SGP4 rows (Earth satellites) are only good near their epoch, so they carry a
 * tight validity window the propagation gate hides them outside of. The real
 * chunk overwrites it once it lands. Keplerian and parabolic orbits have no
 * hard cutoff.
 */
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
