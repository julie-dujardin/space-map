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
	[ObjectType.MOON]: 1
};

export function minCameraDistance(body: PositionedBody): number {
	const radiusKm = effectiveRadiusKm(body.data);
	const fixed = SURFACE_CLEARANCE_KM[body.data.objectType];
	// Spacecraft/debris span ~0.3 m to ~100 m; a fixed clearance would block
	// close approach to tiny craft. Scale it with the body so max zoom-in is
	// always proportional to real size.
	const clearance = fixed ?? radiusKm * 0.25;
	return kmToScene(radiusKm + clearance);
}
