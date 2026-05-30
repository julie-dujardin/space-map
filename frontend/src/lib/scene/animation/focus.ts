import { Matrix4, Quaternion, Vector3, type PerspectiveCamera } from 'three';
import type { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import type { Vec3 } from './math';
import { f64lerp } from './math';

export const FOCUS_DURATION_MS = 350;
export const FLY_DURATION_MS = 1600;

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
	flyQ0: Quaternion | null;
	flyQ1: Quaternion | null;
	orbitFly: boolean;
	focusStartTime: number;
	focusDurationMs: number;
}

const _lookAtMatrix = new Matrix4();
const _lookAtEye = new Vector3();
const _lookAtTarget = new Vector3();
const _lookAtQuat = new Quaternion();
const _slerpQ = new Quaternion();
const _lookAtQ = new Quaternion();

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
			// Ease-in position when approaching from afar, smoothstep when orbiting
			const sCam = focusChanging ? t * t * t : s;
			const camWorld = f64lerp(state.camOriginWorld!, state.camTargetWorld!, sCam);
			camera.position.set(
				camWorld[0] - state.focusTruePos[0],
				camWorld[1] - state.focusTruePos[1],
				camWorld[2] - state.focusTruePos[2]
			);
			if (focusChanging) {
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
				// Already focused: pure lookAt
				camera.lookAt(
					state.focusTargetWorld[0] - state.focusTruePos[0],
					state.focusTargetWorld[1] - state.focusTruePos[1],
					state.focusTargetWorld[2] - state.focusTruePos[2]
				);
			}
		} else {
			// Slerp camera orientation toward a lookAt that tracks the body's *current*
			// position each frame — without this, animation ends pointed at the body's
			// start-of-animation position and snaps when controls re-center on settle.
			const lookAtQ = lookAtQuaternion(state.camOriginWorld!, state.focusTargetWorld, camera.up);
			camera.quaternion.slerpQuaternions(state.flyQ0!, lookAtQ, s);
			// Camera world position eases in so rotation is visible first
			const sCam = t * t * t; // cubic ease-in
			const camWorld = f64lerp(state.camOriginWorld!, state.camTargetWorld!, sCam);
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
		state.flyQ0 = null;
		state.flyQ1 = null;
		state.orbitFly = false;
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
		state.focusDurationMs = FLY_DURATION_MS;
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
	} else {
		// Camera stays at current world position, only rotates toward new focus.
		// camTargetOffset stays null — the camera target is world-fixed (camera
		// doesn't move); the orientation slerp recomputes its lookAt each frame
		// against the body's current position in stepFocusAnimation.
		state.camOriginWorld = cameraTruePos;
		state.camTargetWorld = [...cameraTruePos];
		state.camTargetOffset = null;
		state.focusDurationMs = FOCUS_DURATION_MS;
		state.flyQ0 = camera.quaternion.clone();
		// flyQ1 is unused on this path (orientation slerps to a per-frame lookAt
		// against the body's current position); set it non-null so the isFlying
		// gate in stepFocusAnimation passes.
		state.flyQ1 = state.flyQ0.clone();
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
	// Body-relative offset (focusTruePos == focused body position at this point)
	// so camTargetWorld follows the body during the orbit fly.
	state.camTargetOffset = [
		camPos[0] - state.focusTruePos[0],
		camPos[1] - state.focusTruePos[1],
		camPos[2] - state.focusTruePos[2]
	];
	state.focusOriginWorld = [...state.focusTruePos];
	state.focusTargetWorld = [...state.focusTruePos];
	state.focusStartTime = performance.now();
	state.focusDurationMs = FLY_DURATION_MS;
	state.orbitFly = true;
	// Set dummy quaternions so isFlying is true
	state.flyQ0 = camera.quaternion.clone();
	state.flyQ1 = camera.quaternion.clone();
}
