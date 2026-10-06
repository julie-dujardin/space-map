import {
	ObjectType,
	type BodyData,
	type FeatureAnchor,
	type PositionedBody
} from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';

/** Focus-body id for a feature seat — synthetic, never serialised, just
 *  needs to be stable and distinct from real ids. */
function featureBodyId(hostId: string, featureId: number): string {
	return `feature:${hostId}:${featureId}`;
}

/** Synthesise the orbitable focus body for a surface feature. Orbital elements
 *  are inert: `seatFeatureBody` places it on the host each frame. Carries no
 *  mesh/halo/trail; the host renders the terrain. */
export function makeFeatureBody(anchor: FeatureAnchor, name: string | null): PositionedBody {
	const data: BodyData = {
		id: featureBodyId(anchor.hostId, anchor.featureId),
		name,
		objectType: ObjectType.SURFACE_FEATURE,
		parentId: anchor.hostId,
		radiusKm: NaN,
		hasLocalized: false,
		a: 0,
		e: 0,
		i: 0,
		om: 0,
		w: 0,
		ma: 0,
		n: 0,
		epoch: 0,
		validityStart: -Infinity,
		validityEnd: Infinity,
		orbitalSource: OrbitalSource.UNKNOWN
	};
	return { data, position: null, orbitCenterId: anchor.hostId, featureAnchor: anchor };
}
