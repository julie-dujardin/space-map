import { Matrix4, Quaternion, Vector3, type PerspectiveCamera } from 'three';
import type { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import type { Vec3 } from './math';
import { f64dist, f64lerp, f64slerpArc } from './math';
import {
	angularDuration,
	spatialDuration,
	FLY_ROT_PACING,
	FLY_TRANS_PACING,
	FOCUS_ROT_PACING
} from './pacing';

/** Initial-state default before the first real animation kicks in. */
export const FOCUS_DURATION_MS = FOCUS_ROT_PACING.refMs;

export interface FocusState {
	focusTruePos: Vec3;
	focusOriginWorld: Vec3;
	focusTargetWorld: Vec3;
	camOriginWorld: Vec3 | null;
	camTargetWorld: Vec3 | null;
	/**
	 * Offset of `camTargetWorld` relative to the focused body's position. When set,
	 * the renderer refreshes `camTargetWorld = body.position + camTargetOffset` every
	 * frame so the fly target tracks a moving body. Null when the camera target is
	 * world-fixed (e.g. focus-rotation without a fly).
	 */
	camTargetOffset: Vec3 | null;
	/**
	 * Body-relative offset of `camOriginWorld`, mirroring {@link camTargetOffset}.
	 * Set for arc-orbit re-frames so the arc's start point tracks the moving body
	 * each frame — without it the arc center (the body) drifts away from a fixed
	 * world origin at high sim speed, ballooning the radius and swinging the camera
	 * out and back. Null when the origin is world-fixed (approach flies from afar).
	 */
	camOriginOffset: Vec3 | null;
	flyQ0: Quaternion | null;
	flyQ1: Quaternion | null;
	orbitFly: boolean;
	/** Camera circles the focus center at constant radius (arc, not chord) instead
	 *  of a straight lerp — set when re-framing on the already-focused body (e.g.
	 *  switching surface features) so the path doesn't cut through the planet. */
	arcOrbit: boolean;
	/** Lock camera world position to `camTargetWorld` (body-tracking) for the
	 *  whole animation instead of easing from `camOriginWorld` — for plain focus
	 *  switches the `focusTruePos` smoothstep alone carries the scene transition. */
	cameraStaysOnBody: boolean;
	focusStartTime: number;
	focusDurationMs: number;
}

const _lookAtMatrix = new Matrix4();
const _lookAtEye = new Vector3();
const _lookAtTarget = new Vector3();
const _lookAtQuat = new Quaternion();
const _slerpQ = new Quaternion();
const _lookAtQ = new Quaternion();
const _forwardA = new Vector3();
const _forwardB = new Vector3();

/** Compute the orientation a camera at `eye` would have when looking at `target`, without mutating any camera. */
function lookAtQuaternion(eye: Vec3, target: Vec3, up: Vector3): Quaternion {
	_lookAtEye.set(eye[0], eye[1], eye[2]);
	_lookAtTarget.set(target[0], target[1], target[2]);
	_lookAtMatrix.lookAt(_lookAtEye, _lookAtTarget, up);
	return _lookAtQuat.setFromRotationMatrix(_lookAtMatrix).clone();
}

/**
 * Advance the focus/fly animation by one frame.
 * Mutates `state`, `camera`, and `controls` in place.
 * Returns whether OrbitControls has settled (no damping movement).
 */
export function stepFocusAnimation(
	state: FocusState,
	camera: PerspectiveCamera,
	controls: OrbitControls,
	repositionAll: () => void,
	rebuildPointCloudBasis: () => void
): boolean {
	const elapsed = performance.now() - state.focusStartTime;
	const t = Math.min(elapsed / state.focusDurationMs, 1);
	const isAnimating = t < 1;
	const isFlying = !!(state.camOriginWorld && state.camTargetWorld && state.flyQ0 && state.flyQ1);

	if (isAnimating && isFlying) {
		const s = t * t * (3 - 2 * t); // smoothstep
		// Lerp focus position in Float64
		state.focusTruePos = f64lerp(state.focusOriginWorld, state.focusTargetWorld, s);
		repositionAll();
		if (state.orbitFly) {
			const focusChanging =
				state.focusOriginWorld[0] !== state.focusTargetWorld[0] ||
				state.focusOriginWorld[1] !== state.focusTargetWorld[1] ||
				state.focusOriginWorld[2] !== state.focusTargetWorld[2];
			let camWorld: Vec3;
			if (state.arcOrbit) {
				// Re-framing the already-focused body: sweep around its center at
				// constant radius so the path can't cut a chord through the planet.
				// (focusChanging is polluted true here by per-frame body motion, so
				// gate on the explicit flag, not on it.)
				camWorld = f64slerpArc(
					state.camOriginWorld!,
					state.camTargetWorld!,
					state.focusTargetWorld,
					s
				);
			} else {
				// Approaching from afar: ease position in so the rotation reads first.
				const sCam = focusChanging ? t * t * t : s;
				camWorld = f64lerp(state.camOriginWorld!, state.camTargetWorld!, sCam);
			}
			camera.position.set(
				camWorld[0] - state.focusTruePos[0],
				camWorld[1] - state.focusTruePos[1],
				camWorld[2] - state.focusTruePos[2]
			);
			if (focusChanging && !state.arcOrbit) {
				// Approaching: blend from slerp (turn) to lookAt (keep centered)
				camera.quaternion.slerpQuaternions(state.flyQ0!, state.flyQ1!, s);
				_slerpQ.copy(camera.quaternion);
				camera.lookAt(
					state.focusTargetWorld[0] - state.focusTruePos[0],
					state.focusTargetWorld[1] - state.focusTruePos[1],
					state.focusTargetWorld[2] - state.focusTruePos[2]
				);
				_lookAtQ.copy(camera.quaternion);
				camera.quaternion.slerpQuaternions(_slerpQ, _lookAtQ, s);
			} else {
				// Orbiting in place: pure lookAt keeps the body centered throughout.
				camera.lookAt(
					state.focusTargetWorld[0] - state.focusTruePos[0],
					state.focusTargetWorld[1] - state.focusTruePos[1],
					state.focusTargetWorld[2] - state.focusTruePos[2]
				);
			}
		} else {
			let camWorld: Vec3;
			if (state.cameraStaysOnBody) {
				camWorld = state.camTargetWorld!;
			} else {
				// Camera world position eases in so rotation is visible first
				const sCam = t * t * t; // cubic ease-in
				camWorld = f64lerp(state.camOriginWorld!, state.camTargetWorld!, sCam);
			}
			// Slerp toward a lookAt recomputed each frame from the actual camera
			// world position; freezing the source would drift the body off-centre
			// when the camera is body-tracking.
			const lookAtQ = lookAtQuaternion(camWorld, state.focusTargetWorld, camera.up);
			camera.quaternion.slerpQuaternions(state.flyQ0!, lookAtQ, s);
			camera.position.set(
				camWorld[0] - state.focusTruePos[0],
				camWorld[1] - state.focusTruePos[1],
				camWorld[2] - state.focusTruePos[2]
			);
		}
		// Skip controls.update() — we're driving the camera directly
		return false;
	}

	// Animation complete or not flying — settle to target
	if (
		state.focusTruePos[0] !== state.focusTargetWorld[0] ||
		state.focusTruePos[1] !== state.focusTargetWorld[1] ||
		state.focusTruePos[2] !== state.focusTargetWorld[2]
	) {
		state.focusTruePos = [...state.focusTargetWorld];
		repositionAll();
		// Rebuild point cloud vertex buffers relative to new focus
		rebuildPointCloudBasis();
	}
	controls.target.set(0, 0, 0);
	if (state.camTargetWorld) {
		const cx = state.camTargetWorld[0] - state.focusTruePos[0];
		const cy = state.camTargetWorld[1] - state.focusTruePos[1];
		const cz = state.camTargetWorld[2] - state.focusTruePos[2];
		camera.position.set(cx, cy, cz);
		// Flush stale OrbitControls damping delta accumulated during the fly
		controls.enableDamping = false;
		controls.update();
		controls.enableDamping = true;
		camera.position.set(cx, cy, cz);
		state.camOriginWorld = null;
		state.camTargetWorld = null;
		state.camTargetOffset = null;
		state.camOriginOffset = null;
		state.flyQ0 = null;
		state.flyQ1 = null;
		state.orbitFly = false;
		state.arcOrbit = false;
		state.cameraStaysOnBody = false;
	}
	return !controls.update();
}

/** Compute focus animation state for transitioning to a new body. */
export function prepareFocusTarget(
	state: FocusState,
	bodyPosition: Vec3,
	camera: PerspectiveCamera,
	cameraTruePos: Vec3,
	camPos?: Vec3
): void {
	state.focusOriginWorld = [...state.focusTruePos];
	state.focusTargetWorld = [...bodyPosition];
	state.focusStartTime = performance.now();
	// Arc-orbit is only for re-framing the already-focused body; a new-body focus
	// (incl. the orbitFly approach set by the controller) must use the linear path.
	state.arcOrbit = false;
	// Approach flies leave from a fixed world point; only arc-orbit tracks the origin.
	state.camOriginOffset = null;

	if (camPos) {
		state.camOriginWorld = cameraTruePos;
		state.camTargetWorld = [...camPos];
		// Body-relative offset so camTargetWorld can be refreshed each frame as the
		// body moves; the relative direction (and therefore flyQ1) stays valid.
		state.camTargetOffset = [
			camPos[0] - bodyPosition[0],
			camPos[1] - bodyPosition[1],
			camPos[2] - bodyPosition[2]
		];
		state.cameraStaysOnBody = false;
		// Capture start orientation, compute end orientation for slerp
		state.flyQ0 = camera.quaternion.clone();
		const savedPos = camera.position.clone();
		// Temporarily place camera at target in focus-relative space (using CURRENT focusTruePos)
		camera.position.set(
			camPos[0] - state.focusTruePos[0],
			camPos[1] - state.focusTruePos[1],
			camPos[2] - state.focusTruePos[2]
		);
		// lookAt target body in focus-relative space
		camera.lookAt(
			bodyPosition[0] - state.focusTruePos[0],
			bodyPosition[1] - state.focusTruePos[1],
			bodyPosition[2] - state.focusTruePos[2]
		);
		state.flyQ1 = camera.quaternion.clone();
		camera.position.copy(savedPos);
		camera.quaternion.copy(state.flyQ0);
		// Pace by whichever of {linear travel, rotation} is larger — a small move
		// with a big turn shouldn't snap; a big move with a small turn shouldn't drag.
		const dist = f64dist(cameraTruePos, camPos);
		const angle = state.flyQ0.angleTo(state.flyQ1);
		state.focusDurationMs = Math.max(
			spatialDuration(dist, FLY_TRANS_PACING),
			angularDuration(angle, FLY_ROT_PACING)
		);
	} else {
		// Camera tracks the new body via camTargetOffset so small systems with
		// large solar velocity (asteroids at fast time) don't slip away during
		// the rotation.
		state.camOriginWorld = cameraTruePos;
		state.camTargetWorld = [...cameraTruePos];
		state.camTargetOffset = [
			cameraTruePos[0] - bodyPosition[0],
			cameraTruePos[1] - bodyPosition[1],
			cameraTruePos[2] - bodyPosition[2]
		];
		state.cameraStaysOnBody = true;
		state.flyQ0 = camera.quaternion.clone();
		// flyQ1 is unused on this path (orientation slerps to a per-frame lookAt
		// against the body's current position); set it non-null so the isFlying
		// gate in stepFocusAnimation passes.
		state.flyQ1 = state.flyQ0.clone();
		// Pace by the angle from current camera forward to the new body direction —
		// that's what the per-frame lookAt slerp is actually sweeping through.
		_forwardA.set(0, 0, -1).applyQuaternion(state.flyQ0);
		_forwardB
			.set(
				bodyPosition[0] - cameraTruePos[0],
				bodyPosition[1] - cameraTruePos[1],
				bodyPosition[2] - cameraTruePos[2]
			)
			.normalize();
		const angle = _forwardA.angleTo(_forwardB);
		state.focusDurationMs = angularDuration(angle, FOCUS_ROT_PACING);
	}
}

/** Start a fly-to animation around the current focus body (orbit), keeping it centered. */
export function prepareFlyToCamera(
	state: FocusState,
	camera: PerspectiveCamera,
	cameraTruePos: Vec3,
	camPos: Vec3
): void {
	state.camOriginWorld = cameraTruePos;
	state.camTargetWorld = [...camPos];
	// Body-relative offsets (focusTruePos == focused body position at this point)
	// so BOTH arc endpoints follow the body during the orbit fly. Tracking the
	// origin too keeps the arc center (the body) at a constant distance from both
	// ends, so the body stays framed even when it travels far at high sim speed.
	state.camTargetOffset = [
		camPos[0] - state.focusTruePos[0],
		camPos[1] - state.focusTruePos[1],
		camPos[2] - state.focusTruePos[2]
	];
	state.camOriginOffset = [
		cameraTruePos[0] - state.focusTruePos[0],
		cameraTruePos[1] - state.focusTruePos[1],
		cameraTruePos[2] - state.focusTruePos[2]
	];
	state.focusOriginWorld = [...state.focusTruePos];
	state.focusTargetWorld = [...state.focusTruePos];
	state.focusStartTime = performance.now();
	state.orbitFly = true;
	state.arcOrbit = true;
	state.cameraStaysOnBody = false;
	// Set dummy quaternions so isFlying is true
	state.flyQ0 = camera.quaternion.clone();
	state.flyQ1 = camera.quaternion.clone();
	// Pace by translation distance or by the angular sweep around the focus
	// (the camera lookAt re-targets each frame, so this is how much it'll rotate).
	const dist = f64dist(cameraTruePos, camPos);
	_forwardA
		.set(
			state.focusTruePos[0] - cameraTruePos[0],
			state.focusTruePos[1] - cameraTruePos[1],
			state.focusTruePos[2] - cameraTruePos[2]
		)
		.normalize();
	_forwardB
		.set(
			state.focusTruePos[0] - camPos[0],
			state.focusTruePos[1] - camPos[1],
			state.focusTruePos[2] - camPos[2]
		)
		.normalize();
	const angle = _forwardA.angleTo(_forwardB);
	state.focusDurationMs = Math.max(
		spatialDuration(dist, FLY_TRANS_PACING),
		angularDuration(angle, FLY_ROT_PACING)
	);
}
