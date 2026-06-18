import { ObjectType, isAsteroid, type BodyData, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { orbitalElementsToPosition, parabolicToPosition } from '$lib/math/orbit/position';
import { buildSatrec, sgp4PositionScene } from '$lib/math/orbit/sgp4';
import { AU_KM } from '$lib/math/units';
import { dateToJD } from '$lib/format/date';
import { fetchLabels } from '$lib/fetch/position/labels';
import { MinorBucket } from '$lib/fetch/position/minor-columns';
import type { ChunkLoader } from '$lib/fetch/position/chunk';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';

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
 * Create placeholder PositionedBodies from the __global__ object file. When
 * the target's parent isn't yet in `loader.positions` (e.g. URL-loading a
 * moon-of-asteroid before phase 2 lands the host asteroid's chunk), recurses
 * up the chain — each ancestor placeholder is added to the returned list AND
 * registered in `loader.positions` so the target can anchor on a real point
 * rather than the SSB. Returns an empty array when the chain can't close
 * (missing global data, missing orbit, cycle), in which case the body is
 * silently hidden until its real chunk lands. The last entry is always the
 * target; earlier entries (if any) are ancestors the caller should also
 * route.
 *
 * Each entry's `zone` is the SBDB-class zone id (e.g. `"APO"`) used for
 * routing — null when the body has no SBDB record (moons, majors), in which
 * case the caller falls back to `parentId`-based routing (spacecraft/debris)
 * or `bodiesById` (majors / moons).
 */
export async function createPlaceholderBody(
	targetId: string,
	date: Date,
	loader: ChunkLoader,
	visited: Set<string> = new Set()
): Promise<Array<{ body: PositionedBody; zone: string | null }>> {
	if (visited.has(targetId)) {
		console.warn(`createPlaceholderBody: cycle detected at ${targetId} — hiding`);
		return [];
	}
	visited.add(targetId);
	let detail: Awaited<ReturnType<typeof fetchObjectDetail>>;
	try {
		detail = await fetchObjectDetail(targetId);
	} catch {
		console.warn(`createPlaceholderBody: failed to fetch global data for ${targetId} — hiding`);
		return [];
	}
	const global = detail.global;
	if (!global?.orbit) {
		console.warn(`createPlaceholderBody: no orbit data for ${targetId} — hiding`);
		return [];
	}

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

	const ancestors: Array<{ body: PositionedBody; zone: string | null }> = [];
	let parentPos = loader.positions.get(orbit.parent_id);
	if (!parentPos) {
		// Recurse up the chain so e.g. a moon-of-asteroid can anchor on a
		// placeholder of its host before the asteroid's real chunk lands. The
		// recursive call registers the parent's position in `loader.positions`
		// (via the `loader.positions.set` below) so siblings down the chain
		// share the same anchor. If the chain can't close — the parent has no
		// global data or no orbit — hide rather than dump at SSB (the old
		// fallback placed asteroid moons at the origin, visually orbiting the
		// Sun-system center instead of their host).
		const parentChain = await createPlaceholderBody(orbit.parent_id, date, loader, visited);
		if (parentChain.length === 0) {
			console.warn(
				`createPlaceholderBody: parent ${orbit.parent_id} of ${targetId} not resolvable — hiding`
			);
			return [];
		}
		const parentEntry = parentChain[parentChain.length - 1];
		parentPos = parentEntry.body.position;
		loader.positions.set(orbit.parent_id, parentPos);
		ancestors.push(...parentChain);
	}
	const offset = satrec
		? sgp4PositionScene(satrec, dateToJD(date))
		: isParabolic
			? parabolicToPosition(data, date)
			: orbitalElementsToPosition(data, date);
	if (!offset) {
		console.warn(`Failed to compute position for ${targetId} (e=${data.e})`);
		return ancestors;
	}
	const position: [number, number, number] = [
		parentPos[0] + offset[0],
		parentPos[1] + offset[1],
		parentPos[2] + offset[2]
	];

	ancestors.push({
		body: { data, position, orbitElements: data, orbitCenter: parentPos },
		zone: global.sbdb?.class ?? null
	});
	return ancestors;
}

/**
 * Stream a single target into the running scene if absent — the in-session
 * equivalent of {@link loadScene}'s URL-target placeholder pass (no reload).
 * Routes by type like loadScene; earth-sat placeholders reconcile on the next
 * zone-refresher swap, probes keep theirs and draw from probeStore.
 */
export async function ensureTargetStreamed(
	ctx: ContextManager,
	targetId: string,
	date: Date,
	loader: ChunkLoader
): Promise<void> {
	if (ctx.getBody(targetId)) return;
	const placeholders = await createPlaceholderBody(targetId, date, loader);
	if (placeholders.length === 0) return;

	const labels = await fetchLabels();
	const asteroidBucket = (zone: string): MinorBucket => {
		let b = ctx.bodies.asteroidBodiesByZone.get(zone);
		if (!b) ctx.bodies.asteroidBodiesByZone.set(zone, (b = new MinorBucket(labels)));
		return b;
	};
	const spacecraftBucket = (key: string): Map<string, PositionedBody> => {
		let b = ctx.bodies.spacecraftByParent.get(key);
		if (!b) ctx.bodies.spacecraftByParent.set(key, (b = new Map()));
		return b;
	};
	const added: string[] = [];

	for (let i = 0; i < placeholders.length; i++) {
		const { body, zone } = placeholders[i];
		if (ctx.getBody(body.data.id)) continue;
		const type = body.data.objectType;
		const parentEntry = i > 0 ? placeholders[i - 1] : null;
		const resolvedZone =
			type === ObjectType.MOON && parentEntry && isAsteroid(parentEntry.body.data.objectType)
				? 'small_body_moons'
				: zone;
		if (type === ObjectType.SPACECRAFT || type === ObjectType.DEBRIS) {
			const key = body.data.parentId;
			spacecraftBucket(key).set(body.data.id, body);
			ctx.bodies.dirtySpacecraftGroups.add(key);
			added.push(body.data.id);
		} else if (resolvedZone) {
			asteroidBucket(resolvedZone).addPlaceholder(body);
			ctx.bodies.dirtyAsteroidZones.add(resolvedZone);
			added.push(body.data.id);
		} else {
			ctx.bodies.addBodies([body]);
		}
		ctx.credits.recordOrbitSources([body]);
	}

	// Re-wrap the outer Maps so reactive observers see a new ref, then notify the
	// promotion registry so the freshly-added bodies get a visual representation.
	ctx.bodies.asteroidBodiesByZone = new Map(ctx.bodies.asteroidBodiesByZone);
	ctx.bodies.spacecraftByParent = new Map(ctx.bodies.spacecraftByParent);
	ctx.bodies.minorBodyVersion++;
	if (added.length > 0) ctx.bodies.notifyBodiesAdded(added);
}
