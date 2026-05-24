import { ObjectType, type BodyData, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { orbitalElementsToPosition, parabolicToPosition } from '$lib/math/orbit/position';
import { buildSatrec, sgp4PositionScene } from '$lib/math/orbit/sgp4';
import { AU_KM } from '$lib/math/units';
import { dateToJD } from '$lib/format/date';
import type { ChunkLoader } from '$lib/fetch/position/chunk';

/** Map a GlobalObjectData.type string (e.g. "asteroid_main_belt") to the ObjectType enum. */
function parseObjectType(typeStr: string): ObjectType {
	const key = typeStr.toUpperCase() as keyof typeof ObjectType;
	return ObjectType[key] ?? ObjectType.UNDOCUMENTED;
}

/**
 * Map a global JSON `orbit.source` string (the lowercase `OrbitalSource` enum
 * value) back to the numeric ordinal — placeholder bodies created before their
 * chunk lands have no binary header to pull from, so we parse the string.
 * Returns `UNKNOWN` if the server sent a value the frontend doesn't know.
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
 * Create a placeholder PositionedBody from the __global__ object file along
 * with the SBDB-class zone id (e.g. `"MBA"`) for routing — null when the
 * object has no SBDB record, in which case the caller falls back to
 * `parentId`-based routing (spacecraft/debris) or `bodiesById` (majors).
 *
 * Returns null if the object doesn't exist or has no orbit data.
 */
export async function createPlaceholderBody(
	targetId: string,
	date: Date,
	loader: ChunkLoader
): Promise<{ body: PositionedBody; zone: string | null } | null> {
	let detail: Awaited<ReturnType<typeof fetchObjectDetail>>;
	try {
		detail = await fetchObjectDetail(targetId);
	} catch {
		console.warn(`Failed to fetch global data for ${targetId}`);
		return null;
	}
	const global = detail.global;
	if (!global?.orbit) return null;

	const orbit = global.orbit;
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

	// SGP4 placeholders (URL-navigated Earth sats arriving before the chunk)
	// need a tight validity window so the per-frame propagation gate hides
	// them when the sim time wanders far from epoch — the chunk's real window
	// will overwrite this once it loads. Keplerian/parabolic orbits have no
	// hard cutoff, so leave them unbounded.
	const SGP4_VALIDITY_SLACK_DAYS = 14;
	const validityStart = satrec ? orbit.epoch_jd - SGP4_VALIDITY_SLACK_DAYS : -Infinity;
	const validityEnd = satrec ? orbit.epoch_jd + SGP4_VALIDITY_SLACK_DAYS : Infinity;

	const data: BodyData = {
		id: targetId,
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
		// Planet-scale means CelesTrak TLE data, which uses Earth-equatorial angles.
		equatorial: isPlanetScale,
		validityStart,
		validityEnd,
		orbitalSource: parseOrbitalSource(orbit.source),
		...(isParabolic ? { q: orbit.q, tp: orbit.tp } : {}),
		...(satrec ? { satrec } : {})
	};

	const parentPos = loader.positions.get(orbit.parent_id) ?? [0, 0, 0];
	const offset = satrec
		? sgp4PositionScene(satrec, dateToJD(date))
		: isParabolic
			? parabolicToPosition(data, date)
			: orbitalElementsToPosition(data, date);
	if (!offset) {
		console.warn(`Failed to compute position for ${targetId} (e=${data.e})`);
		return null;
	}
	const position: [number, number, number] = [
		parentPos[0] + offset[0],
		parentPos[1] + offset[1],
		parentPos[2] + offset[2]
	];

	return {
		body: { data, position, orbitElements: data, orbitCenter: parentPos },
		zone: global.sbdb?.class ?? null
	};
}
