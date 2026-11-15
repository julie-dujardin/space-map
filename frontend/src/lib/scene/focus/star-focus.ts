import { ObjectType, type BodyData, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { extrasolarObjectId } from '$lib/fetch/extrasolar/ids';
import { pointOf } from '$lib/fetch/extrasolar/systems';
import {
	SYSTEM_SLUG,
	astrometricOrbit,
	homeRow,
	type ExtrasolarRecord
} from '$lib/fetch/extrasolar/lookup';
import { isGalaxy } from '$lib/fetch/extrasolar/galaxies';
import { galacticNorthVector } from '$lib/scene/camera/north-reference';
import { planeView } from '$lib/scene/exoplanets/view';
import { PC_SCENE } from '$lib/scene/starfield/tree';
import {
	drawnAbsoluteG,
	renderBpRp,
	starPlace,
	starRadiusKm,
	starTeff
} from '$lib/scene/starfield/record';

/** The camera's distance from a star it frames, scene units: 1,000 AU. A
 *  star there outshines the sky around it, and its neighbours stay a sky. */
export const STAR_VIEW_DISTANCE = 1e4;

/** The camera's distance from the point of a galaxy it frames, scene units:
 *  60 kpc. The disc of the Milky Way then fits the width of a phone screen. */
export const GALAXY_VIEW_DISTANCE = 6e4 * PC_SCENE;

/** The camera place that frames an extrasolar object with no planetary system
 *  to show. A star has a distance only. A galaxy is seen from above the
 *  Galactic plane, the one plane of a disc that the scene knows. */
export function extrasolarView(body: PositionedBody): {
	distance: number;
	latitude?: number;
	longitude?: number;
} {
	const extrasolar = body.extrasolar;
	if (!extrasolar?.scene || !isGalaxy(extrasolar.record)) return { distance: STAR_VIEW_DISTANCE };
	const pole = galacticNorthVector();
	return planeView(extrasolar.scene, [pole.x, pole.y, pole.z], GALAXY_VIEW_DISTANCE);
}

/** The starfield draws extrasolar bodies at their catalogue positions. A
 *  resolved system, a held star or a galaxy has a place but no point, so it
 *  draws nothing, and has no radius for the camera to frame: a held star takes
 *  its radius where its system draws it (`holdStarSystem`). The Metadata row
 *  gives the radius and says whether the object bundles hold a localized entry. */
export function makeStarBody(record: ExtrasolarRecord): PositionedBody {
	const home = homeRow(record);
	const orbit = astrometricOrbit(record);
	const place = home ? starPlace(home, orbit) : null;
	const pointless = record.home === SYSTEM_SLUG || isGalaxy(record);
	const radiusKm = pointless ? null : starRadiusKm(record.metadata);
	const data: BodyData = {
		id: extrasolarObjectId(record.id),
		name: record.metadata.name,
		objectType: ObjectType.EXTRASOLAR,
		parentId: '',
		radiusKm: radiusKm ?? NaN,
		hasLocalized: record.metadata.object,
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
	return {
		data,
		position: null,
		extrasolar: {
			id: record.id,
			record,
			scene: place?.scene ?? null,
			tree: pointless ? null : (place?.tree ?? null),
			absMag: home ? drawnAbsoluteG(home, orbit) : null,
			point: pointOf(record),
			colour: home ? renderBpRp(home) : null,
			radiusKm,
			teff: home ? starTeff(home) : null
		}
	};
}
