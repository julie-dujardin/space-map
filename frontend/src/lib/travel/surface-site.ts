/**
 * Where a surface feature is, as the trajectory kernel wants it.
 *
 * The kernel draws a landing all the way to its site, but stays free of
 * rotation models — it takes the site as a function of time and this module is
 * that function: IAU pole + spin off the body's detail bundle, the same maths
 * that orients the rendered globe, so the arc ends on the feature's label
 * rather than near it.
 */

import { Vector3 } from 'three';
import { bodyQuaternion, type NutPrec } from '$lib/math/orientation';
import { bodyFixedUnit } from '$lib/scene/position/rendered-surface';
import { effectiveRadiusKm, type BodyData } from '$lib/types/objects';
import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
import { getNutPrecAngles, ownerIdFor } from '$lib/fetch/systems-global';
import { naifId } from '$lib/travel/travel-body';
import type { Vec3 } from '$lib/math/travel/vec3';

const DEG2RAD = Math.PI / 180;

/**
 * The site's position from the body's centre, km, in ecliptic J2000 axes, at a
 * given date. Null when the body ships no spin model — the kernel then lands at
 * the point its own geometry prefers, which still reaches the ground.
 */
export function surfaceSiteAt(
	body: BodyData,
	detail: GlobalObjectData | null | undefined,
	latDeg: number,
	lonDeg: number
): ((jd: number) => Vec3 | null) | null {
	const orientation = detail?.orientation;
	if (!orientation) return null;
	const radiusKm = effectiveRadiusKm(body);
	if (!(radiusKm > 0)) return null;
	const id = naifId(body.id);
	const angles = id !== null ? getNutPrecAngles(ownerIdFor(id)) : undefined;
	const nutPrec: NutPrec | undefined =
		detail.nut_prec && angles ? { ...detail.nut_prec, angles } : undefined;
	const unit = bodyFixedUnit(latDeg * DEG2RAD, lonDeg * DEG2RAD);
	const v = new Vector3();
	return (jd) => {
		v.set(unit[0], unit[1], unit[2]).applyQuaternion(bodyQuaternion(orientation, jd, nutPrec));
		// Scene axes back to ecliptic: the inverse of `eclipticToScene`.
		return [v.x * radiusKm, -v.z * radiusKm, v.y * radiusKm];
	};
}
