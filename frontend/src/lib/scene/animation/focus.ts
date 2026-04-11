import type { PerspectiveCamera, Quaternion } from 'three';
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
	flyQ0: Quaternion | null;
	flyQ1: Quaternion | null;
	orbitFly: boolean;
	focusStartTime: number;
	focusDurationMs: number;
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
				const slerpQ = camera.quaternion.clone();
				camera.lookAt(
					state.focusTargetWorld[0] - state.focusTruePos[0],
					state.focusTargetWorld[1] - state.focusTruePos[1],
					state.focusTargetWorld[2] - state.focusTruePos[2]
				);
				const lookAtQ = camera.quaternion.clone();
				camera.quaternion.slerpQuaternions(slerpQ, lookAtQ, s);
			} else {
				// Already focused: pure lookAt
				camera.lookAt(
					state.focusTargetWorld[0] - state.focusTruePos[0],
					state.focusTargetWorld[1] - state.focusTruePos[1],
					state.focusTargetWorld[2] - state.focusTruePos[2]
				);
			}
		} else {
			// Slerp camera orientation for uniform angular velocity
			camera.quaternion.slerpQuaternions(state.flyQ0!, state.flyQ1!, s);
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
		state.camTargetWorld = camPos;
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
		// Camera stays at current world position, only rotates toward new focus
		state.camOriginWorld = cameraTruePos;
		state.camTargetWorld = [...cameraTruePos];
		state.focusDurationMs = FOCUS_DURATION_MS;
		// Compute orientation slerp: current → looking at new focus body
		state.flyQ0 = camera.quaternion.clone();
		const savedPos = camera.position.clone();
		const savedQ = camera.quaternion.clone();
		// Temporarily place camera at final focus-relative position to compute lookAt
		camera.position.set(
			cameraTruePos[0] - bodyPosition[0],
			cameraTruePos[1] - bodyPosition[1],
			cameraTruePos[2] - bodyPosition[2]
		);
		camera.lookAt(0, 0, 0);
		state.flyQ1 = camera.quaternion.clone();
		camera.position.copy(savedPos);
		camera.quaternion.copy(savedQ);
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
	state.camTargetWorld = camPos;
	state.focusOriginWorld = [...state.focusTruePos];
	state.focusTargetWorld = [...state.focusTruePos];
	state.focusStartTime = performance.now();
	state.focusDurationMs = FLY_DURATION_MS;
	state.orbitFly = true;
	// Set dummy quaternions so isFlying is true
	state.flyQ0 = camera.quaternion.clone();
	state.flyQ1 = camera.quaternion.clone();
}
