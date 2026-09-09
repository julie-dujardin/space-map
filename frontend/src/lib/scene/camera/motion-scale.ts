import { MathUtils, type PerspectiveCamera } from 'three';
import { effectiveRadiusKm, type PositionedBody } from '$lib/types/objects';
import { kmToScene } from '$lib/math/units';
import { isModelBearing } from '$lib/scene/objects/body/model';
import type { Vec3 } from '$lib/scene/animation/math';

/** Floor on {@link MotionScale.translate}: the surface clamp can seat the camera
 *  on the ground, where an unfloored scale would freeze the gesture. */
const MIN_TRANSLATE_SCALE = 0.02;

/** Guard on {@link MotionScale.rotate} for a camera at or under the surface.
 *  Small enough that the 1:1 rate governs everywhere it is defined — even a
 *  1000 km station over the Sun still asks for ~2e-4. */
const MIN_ROTATE_SCALE = 1e-4;

/** Speed factors for the OrbitControls gestures at the camera's current station. */
export interface MotionScale {
	/** `rotateSpeed`. */
	rotate: number;
	/** `panSpeed` and `zoomSpeed` — both are proportional to the orbit radius. */
	translate: number;
}

/**
 * Rescales the OrbitControls speeds, which all key off the orbit radius — and
 * the orbit target is the focused body's *centre*. A camera 10 km over Mars
 * still swings on a 3400 km lever arm and zooms in 170 km steps, though what
 * fills its screen is the ground just below.
 *
 * `translate` converts pan and zoom from centre-relative to ground-relative:
 * the clearance above the nearest surface over the orbit radius. The surfaces
 * in reach are the focused object's and its collision `parent`'s (skimming
 * Earth while focused on the ISS).
 *
 * `rotate` instead pins the drag to the ground 1:1, the way a slippy map moves
 * under the pointer. A drag of `p` px over a viewport `H` px tall turns the
 * camera by `2π·p·rotateSpeed/H`; that sweeps the sub-camera point along an arc
 * of `R` per radian and shows it magnified by `H/2/tan(fov/2)` per radian of
 * clearance, so the two cancel at `rotate = h·tan(fov/2)/(π·R)`. Past ~7.7
 * radii the ask exceeds three's default rate and the clamp hands the sky back:
 * a body that small on screen wants to be swung around, not tracked.
 *
 * Both readings need a radius that describes what is drawn, so a model-bearing
 * focus (spacecraft, debris) is left out of them: its radius is a nominal
 * stand-in for a craft with no measured size, and its model renders in the
 * overlay at its own camera's scale — untied to the body's scene radius
 * altogether. A parent underneath still counts.
 */
export function cameraMotionScale(
	camera: PerspectiveCamera,
	focusTruePos: Vec3,
	focused: PositionedBody,
	parent: PositionedBody | undefined
): MotionScale {
	const orbitRadius = camera.position.length();
	if (!(orbitRadius > 0)) return { rotate: 1, translate: 1 };

	const sized = isModelBearing(focused) ? undefined : focused;

	let clearance = orbitRadius;
	for (const body of [sized, parent]) {
		if (!body) continue;
		const radiusScene = kmToScene(effectiveRadiusKm(body.data));
		if (!(radiusScene > 0)) continue;
		const dist = Math.hypot(
			camera.position.x - (body.position[0] - focusTruePos[0]),
			camera.position.y - (body.position[1] - focusTruePos[1]),
			camera.position.z - (body.position[2] - focusTruePos[2])
		);
		clearance = Math.min(clearance, dist - radiusScene);
	}

	// The focused body alone drives the rotation: it is the one centred on the
	// orbit target, so its surface is what the drag actually tracks.
	const focusRadius = sized ? kmToScene(effectiveRadiusKm(sized.data)) : 0;
	const halfFovTan = Math.tan(MathUtils.degToRad(camera.getEffectiveFOV()) / 2);
	const rotate =
		focusRadius > 0 ? ((orbitRadius - focusRadius) * halfFovTan) / (Math.PI * focusRadius) : 1;

	return {
		rotate: clamp(rotate, MIN_ROTATE_SCALE),
		translate: clamp(clearance / orbitRadius, MIN_TRANSLATE_SCALE)
	};
}

function clamp(value: number, min: number): number {
	return Math.min(1, Math.max(min, value));
}
