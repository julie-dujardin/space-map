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
import {
	colourBpRp,
	drawnAbsoluteG,
	starPlace,
	starRadiusKm,
	starTeff
} from '$lib/scene/starfield/record';

/** The camera's distance from a star it frames, scene units: 1,000 AU. A
 *  star there outshines the sky around it, and its neighbours stay a sky. */
export const STAR_VIEW_DISTANCE = 1e4;

/** The starfield draws extrasolar bodies at their catalogue positions. A
 *  resolved system or a held star has a place but no point, so it draws
 *  nothing, and has no radius for the camera to frame: a held star takes its
 *  radius where its system draws it (`holdStarSystem`). The Metadata row gives
 *  the radius and says whether the object bundles hold a localized entry. */
export function makeStarBody(record: ExtrasolarRecord): PositionedBody {
	const home = homeRow(record);
	const orbit = astrometricOrbit(record);
	const place = home ? starPlace(home, orbit) : null;
	const pointless = record.home === SYSTEM_SLUG;
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
			colour: home ? colourBpRp(home) : null,
			radiusKm,
			teff: home ? starTeff(home) : null
		}
	};
}
