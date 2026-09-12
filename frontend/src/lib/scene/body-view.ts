/**
 * What a host sees of an object on the map. The scene's own {@link
 * PositionedBody} carries the whole export record — elements, ephemeris
 * buffers, attitude tracks — and none of that is a contract worth freezing, so
 * the public API hands out this view of it instead.
 */

import { ObjectType, type PositionedBody } from '$lib/types/objects';

/** Object kinds a host can act on. The asteroid sub-types collapse into
 *  `asteroid`, whose dynamical family is {@link Body.orbitClass}. */
export type BodyType =
	| 'barycenter'
	| 'lagrange-point'
	| 'star'
	| 'planet'
	| 'dwarf-planet'
	| 'moon'
	| 'asteroid'
	| 'comet'
	| 'spacecraft'
	| 'debris'
	| 'surface-feature'
	| 'unknown';

/** Dynamical family of an asteroid, from its SBDB orbit class. */
export type OrbitClass = 'inner' | 'main-belt' | 'trojan' | 'centaur' | 'tno';

export interface Body {
	/** Export id, as every method that takes a body takes it: `"naif-499"`. */
	id: string;
	/** In the map's reading language; null for a catalogued object with no name. */
	name: string | null;
	type: BodyType;
	/** Only on asteroids. */
	orbitClass?: OrbitClass;
	/** What it orbits, always a major body or a barycentre. */
	parentId: string;
	/** Null where the catalogue quotes no size. */
	radiusKm: number | null;
	/** False while the object has no position at the map's date — outside its
	 *  ephemeris, or catalogued with no orbit at all. Nothing may be framed on
	 *  it: the camera would fly to a stand-in place. */
	placed: boolean;
}

const TYPES: Record<ObjectType, BodyType> = {
	[ObjectType.BARYCENTER]: 'barycenter',
	[ObjectType.LAGRANGE_POINT]: 'lagrange-point',
	[ObjectType.STAR]: 'star',
	[ObjectType.PLANET]: 'planet',
	[ObjectType.DWARF_PLANET]: 'dwarf-planet',
	[ObjectType.MOON]: 'moon',
	[ObjectType.ASTEROID]: 'asteroid',
	[ObjectType.ASTEROID_INNER]: 'asteroid',
	[ObjectType.ASTEROID_MAIN_BELT]: 'asteroid',
	[ObjectType.ASTEROID_TROJAN]: 'asteroid',
	[ObjectType.ASTEROID_CENTAUR]: 'asteroid',
	[ObjectType.ASTEROID_TNO]: 'asteroid',
	[ObjectType.COMET]: 'comet',
	[ObjectType.SPACECRAFT]: 'spacecraft',
	[ObjectType.DEBRIS]: 'debris',
	[ObjectType.UNDOCUMENTED]: 'unknown',
	[ObjectType.SURFACE_FEATURE]: 'surface-feature'
};

const ORBIT_CLASSES: Partial<Record<ObjectType, OrbitClass>> = {
	[ObjectType.ASTEROID_INNER]: 'inner',
	[ObjectType.ASTEROID_MAIN_BELT]: 'main-belt',
	[ObjectType.ASTEROID_TROJAN]: 'trojan',
	[ObjectType.ASTEROID_CENTAUR]: 'centaur',
	[ObjectType.ASTEROID_TNO]: 'tno'
};

/** @internal A snapshot: the scene mutates its own records every frame, so a
 *  host holding one of these is holding what was true when it asked. */
export function bodyView(body: PositionedBody): Body {
	const { id, name, objectType, parentId, radiusKm, unplaceable } = body.data;
	const view: Body = {
		id,
		name,
		type: TYPES[objectType],
		parentId,
		radiusKm: Number.isFinite(radiusKm) && radiusKm > 0 ? radiusKm : null,
		placed: unplaceable !== true && body.positionUnknown !== true
	};
	const orbitClass = ORBIT_CLASSES[objectType];
	if (orbitClass) view.orbitClass = orbitClass;
	return view;
}
