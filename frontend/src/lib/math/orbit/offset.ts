import { ObjectType, isMajorBody, type BodyData, type Unplaced } from '$lib/types/objects';
import { orbitalElementsToPositionJD, parabolicToPositionJD } from '$lib/math/orbit/position';
import { sgp4PositionScene } from '$lib/math/orbit/sgp4';
import { J2000_JD } from '$lib/time/jd';

type Vec3 = [number, number, number];

/** True when the body exists at `jd`: the date is not before its launch or discovery. */
export function existsAt(d: BodyData, jd: number): boolean {
	return !(d.visibleFromDays !== undefined && jd - J2000_JD < d.visibleFromDays);
}

/** True for a row that sits on its parent: a barycentre or a planet with no
 *  offset of its own. Other rows with `a = 0` have no orbit. */
function sitsOnParent(d: BodyData): boolean {
	return (
		d.a === 0 &&
		(d.objectType === ObjectType.BARYCENTER ||
			d.objectType === ObjectType.LAGRANGE_POINT ||
			isMajorBody(d.objectType))
	);
}

/**
 * Offset of an elements-backed body from its parent at `jd`, in scene units,
 * or why it has none. The one place that selects the propagator.
 */
export function elementsOffset(d: BodyData, jd: number): Vec3 | Unplaced {
	if (d.pageOnly) return 'never';
	if (!existsAt(d, jd)) return 'not-yet';
	if (jd < d.validityStart || jd > d.validityEnd) return 'no-data';
	let offset: Vec3 | null;
	const satrec = d.satrec;
	if (satrec) offset = sgp4PositionScene(satrec, jd);
	// An SGP4 row with no record: Kepler elements would draw another orbit.
	else if (d.omm) offset = null;
	else if (d.q != null) offset = parabolicToPositionJD(d, jd);
	else if (d.a === 0) offset = sitsOnParent(d) ? [0, 0, 0] : null;
	else offset = orbitalElementsToPositionJD(d, jd);
	if (!offset || !Number.isFinite(offset[0] + offset[1] + offset[2])) return 'failed';
	return offset;
}
