import { isLowEndDevice } from '$lib/device';
import type { GlobalObjectData } from '$lib/fetch/objects/object-data';

/** Bodies whose shape model should render even though a DEM exists. By default
 *  a displacement map wins (textured relief sphere beats an untextured mesh —
 *  e.g. Dawn's Ceres/Vesta vs their convex lightcurve blobs); list exceptions
 *  here case by case. */
export const PREFER_MODEL_OVER_DEM = new Set<string>([]);

/** Why a body's shape-model bundle isn't the thing on screen. */
export type ShapeModelSkip = 'no-bundle' | 'low-end-device' | 'dem-preferred';

/** Whether the shape-model mesh is what the scene actually draws for this body.
 *  The sources footer credits the mesh off the same answer, so a body whose DEM
 *  sphere wins never advertises a model it doesn't render. */
export function shapeModelSkipReason(
	global: GlobalObjectData | null | undefined
): ShapeModelSkip | null {
	if (!global?.model_name) return 'no-bundle';
	// Rough (non-faithful) meshes barely beat the ellipsoid they replace, so
	// low-end/data-saver clients keep the textured sphere. `render_quality`
	// marks the faithful mission/DEM models as 'high'.
	if (isLowEndDevice() && global.render_quality !== 'high') return 'low-end-device';
	if (global.displacement && !PREFER_MODEL_OVER_DEM.has(global.id)) return 'dem-preferred';
	return null;
}
