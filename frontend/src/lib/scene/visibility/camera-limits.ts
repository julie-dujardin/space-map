import { ObjectType, effectiveRadiusKm, type PositionedBody } from '$lib/types/objects';
import { kmToScene } from '$lib/math/units';

/** Default surface clearance in km, by object type. */
const SURFACE_CLEARANCE_KM: Partial<Record<ObjectType, number>> = {
	[ObjectType.STAR]: 1000,
	[ObjectType.PLANET]: 100,
	[ObjectType.DWARF_PLANET]: 10,
	[ObjectType.ASTEROID]: 0.1,
	[ObjectType.ASTEROID_INNER]: 0.1,
	[ObjectType.ASTEROID_MAIN_BELT]: 0.1,
	[ObjectType.ASTEROID_CENTAUR]: 1,
	[ObjectType.ASTEROID_TROJAN]: 1,
	[ObjectType.ASTEROID_TNO]: 1,
	[ObjectType.COMET]: 1,
	[ObjectType.MOON]: 1,
	[ObjectType.SPACECRAFT]: 0.01
};
const DEFAULT_CLEARANCE_KM = 0.01; // 10 m

/** Per-body overrides for surface clearance (km). Keyed by body id (e.g. "naif-10"). */
const BODY_CLEARANCE_OVERRIDES: Record<string, number> = {};

export function minCameraDistance(body: PositionedBody): number {
	const radiusKm = effectiveRadiusKm(body.data);
	const clearance =
		BODY_CLEARANCE_OVERRIDES[body.data.id] ??
		SURFACE_CLEARANCE_KM[body.data.objectType] ??
		DEFAULT_CLEARANCE_KM;
	return kmToScene(radiusKm + clearance);
}
