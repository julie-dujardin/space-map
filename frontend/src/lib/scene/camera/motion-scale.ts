import { MathUtils, Vector3, type PerspectiveCamera } from 'three';
import { effectiveRadiusKm, type PositionedBody } from '$lib/types/objects';
import { kmToScene } from '$lib/math/units';
import { isModelBearing } from '$lib/scene/objects/body/model';
import type { Vec3 } from '$lib/scene/animation/math';
import { surfaceClearanceKm } from '$lib/scene/visibility/camera-limits';

/** Floor on {@link MotionScale.translate} where no focused surface sets one:
 *  the surface clamp can seat the camera on the ground, where an unfloored
 *  scale would freeze the gesture. */
const MIN_TRANSLATE_SCALE = 0.02;

/** Guard on {@link orthoRotateSpeed} for a disc filling the view many times. */
const MIN_ROTATE_SCALE = 1e-4;

/** Frame time that {@link orbitDamping} applies to. */
export const DAMPING_FRAME_MS = 1000 / 60;

/** OrbitControls inertia per 60 Hz frame. The reduced-motion factor is far
 *  higher so that the camera stops promptly on release (three's default is 0.05). */
export function orbitDamping(reducedMotion: boolean): number {
	return reducedMotion ? 0.4 : 0.05;
}

/** `factor` for a frame of `frameDtMs`. OrbitControls damps once per update,
 *  so a fixed factor makes the inertia last longer at a lower frame rate. */
export function frameDamping(factor: number, frameDtMs: number): number {
	return 1 - (1 - factor) ** (frameDtMs / DAMPING_FRAME_MS);
}

/** The ground under the camera, as the clamps read it. */
export interface MotionGround {
	/** Least clearance in km the clamps keep over `body`. */
	clearanceKm(body: PositionedBody): number;
	/** Distance in km from `body`'s centre to its drawn ground along the unit
	 *  scene-frame `direction`; null reads its sphere. */
	radiusKm(body: PositionedBody, direction: Vector3): number | null;
}

const SPHERE_GROUND: MotionGround = { clearanceKm: surfaceClearanceKm, radiusKm: () => null };

const _toCamera = new Vector3();

/** Speed factors for the OrbitControls gestures at the camera's current station. */
export interface MotionScale {
	/** `rotateSpeed`. */
	rotate: number;
	/** `panSpeed` and `zoomSpeed` — both are proportional to the orbit radius. */
	translate: number;
}

/**
 * The OrbitControls speeds for the camera's station. The orbit pivots on the
 * focused body's centre, so a camera 10 km over Mars would swing on a 3400 km
 * lever and zoom in 170 km steps, though the ground fills its screen.
 *
 * `translate` (pan, zoom) follows the clearance over the nearest drawn ground,
 * the focus's or its collision `parent`'s, so the zoom slows as the ground
 * nears. A `seated` focus stands on its parent's ground already: there the
 * orbit radius is the clearance, and the parent would read the camera's
 * altitude and starve the zoom off the local vertical.
 *
 * `rotate` keeps the ground under a drag moving 1:1 with the pointer, up to
 * three's own rate: a body small on screen is swung round, not tracked.
 *
 * Both read the drawn ground, which can sit kilometres off the body's sphere,
 * and never less than the clearance the clamps keep, where a gesture would
 * freeze. Both read the orbit's `position`, which a middle-drag turn leaves
 * where it is. A craft's radius is a stand-in, so a model-bearing focus is
 * left out of them.
 */
export function cameraMotionScale(
	camera: PerspectiveCamera,
	focusTruePos: Vec3,
	focused: PositionedBody,
	parent: PositionedBody | undefined,
	seated: boolean,
	position: Vector3 = camera.position,
	ground: MotionGround = SPHERE_GROUND
): MotionScale {
	const orbitRadius = position.length();
	if (!(orbitRadius > 0)) return { rotate: 1, translate: 1 };

	const sized = isModelBearing(focused) ? undefined : focused;
	const focusRadius = sized ? kmToScene(effectiveRadiusKm(sized.data)) : 0;
	const floor = focusRadius > 0 ? kmToScene(ground.clearanceKm(sized!)) : 0;

	let clearance = orbitRadius;
	let height = Math.max(orbitRadius - focusRadius, floor);
	for (const body of [sized, seated ? undefined : parent]) {
		const at = body?.position;
		if (!body || !at) continue;
		if (!(effectiveRadiusKm(body.data) > 0)) continue;
		_toCamera.set(
			position.x - (at[0] - focusTruePos[0]),
			position.y - (at[1] - focusTruePos[1]),
			position.z - (at[2] - focusTruePos[2])
		);
		const dist = _toCamera.length();
		const groundKm =
			(dist > 0 && ground.radiusKm(body, _toCamera.divideScalar(dist))) ||
			effectiveRadiusKm(body.data);
		const above = dist - kmToScene(groundKm);
		if (body === sized) height = Math.max(above, floor);
		clearance = Math.min(clearance, body === sized ? height : above);
	}

	// The focused body alone drives the rotation: it is the one centred on the
	// orbit target, so its surface is what the drag actually tracks.
	const halfFovTan = Math.tan(MathUtils.degToRad(camera.getEffectiveFOV()) / 2);
	const rotate = focusRadius > 0 ? (height * halfFovTan) / (Math.PI * focusRadius) : 1;
	const minTranslate =
		floor > 0 ? Math.min(MIN_TRANSLATE_SCALE, floor / orbitRadius) : MIN_TRANSLATE_SCALE;

	return {
		rotate: Math.min(1, rotate),
		translate: clamp(clearance / orbitRadius, minTranslate)
	};
}

function clamp(value: number, min: number): number {
	return Math.min(1, Math.max(min, value));
}

/**
 * `rotateSpeed` that pins a drag to the surface 1:1, as {@link cameraMotionScale}
 * does, for a body drawn under an orthographic camera: `radiusPx` across on a
 * viewport `viewportPx` tall. A drag of `p` px turns it `2π·p·rotateSpeed/viewportPx`
 * radians, and each radian carries the middle of its disc `radiusPx` across.
 */
export function orthoRotateSpeed(radiusPx: number, viewportPx: number): number {
	if (!(radiusPx > 0) || !(viewportPx > 0)) return 1;
	return clamp(viewportPx / (2 * Math.PI * radiusPx), MIN_ROTATE_SCALE);
}
