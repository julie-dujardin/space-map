import { PerspectiveCamera, Quaternion, Vector3 } from 'three';
import type { LookOrbitControls } from '$lib/scene/camera/look-controls';
import { describe, expect, it } from 'vitest';
import {
	prepareAim,
	prepareFlyToCamera,
	prepareFocusTarget,
	stepFocusAnimation,
	type FocusState
} from './focus';

function state(): FocusState {
	return {
		focusTruePos: [0, 0, 0],
		focusOriginWorld: [0, 0, 0],
		focusTargetWorld: [0, 0, 0],
		camOriginWorld: null,
		camTargetWorld: null,
		camTargetOffset: null,
		camOriginOffset: null,
		flyQ0: null,
		orbitFly: false,
		arcOrbit: false,
		cameraStaysOnBody: false,
		aim: null,
		aimLooks: false,
		aimPose: null,
		leavesAim: false,
		focusStartTime: 0,
		focusDurationMs: 0
	};
}

const camera = () =>
	({
		position: new Vector3(0, 0, 5),
		quaternion: new Quaternion(),
		up: new Vector3(0, 1, 0),
		lookAt() {}
	}) as unknown as PerspectiveCamera;

const controls = () =>
	({
		target: new Vector3(),
		enableDamping: true,
		update: () => false
	}) as unknown as LookOrbitControls;

describe('prepareAim', () => {
	it('moves the pivot off the focus and leaves the camera in its place', () => {
		const focus = state();
		const cam = camera();
		const orbit = controls();
		prepareAim(focus, [5, 0, 5], cam, [0, 0, 5], true);
		stepFocusAnimation(
			focus,
			cam,
			orbit,
			() => {},
			() => {}
		);
		expect(orbit.target.toArray()).toEqual([5, 0, 5]);
		expect(cam.position.toArray()).toEqual([0, 0, 5]);
	});

	it('ends at a flight round the focus, which turns back from where it looks', () => {
		const focus = state();
		const cam = new PerspectiveCamera();
		cam.position.set(0, 0, 5);
		cam.lookAt(5, 0, 5);
		const start = cam.quaternion.clone();
		prepareAim(focus, [5, 0, 5], cam, [0, 0, 5], true);
		prepareFlyToCamera(focus, cam, [0, 0, 5], [0, 5, 0]);
		expect(focus.aim).toBeNull();
		expect(focus.focusDurationMs).toBeGreaterThan(0);
		focus.focusStartTime = performance.now();
		stepFocusAnimation(
			focus,
			cam,
			controls(),
			() => {},
			() => {}
		);
		expect(cam.quaternion.angleTo(start)).toBeLessThan(0.1);
	});

	it('eases a flight round the focus in from a view tilted off it', () => {
		const focus = state();
		const cam = new PerspectiveCamera();
		cam.position.set(0, 0, 5);
		cam.lookAt(0, 1, 0);
		prepareFlyToCamera(focus, cam, [0, 0, 5], [0, 5, 0]);
		expect(focus.leavesAim).toBe(true);
		cam.lookAt(0, 0, 0);
		prepareFlyToCamera(focus, cam, [0, 0, 5], [0, 5, 0]);
		expect(focus.leavesAim).toBe(false);
	});

	it('ends at the next focus', () => {
		const focus = state();
		prepareAim(focus, [5, 0, 5], camera(), [0, 0, 5], true);
		prepareFocusTarget(focus, [0, 0, 0], camera(), [0, 0, 5]);
		expect(focus.aim).toBeNull();
	});
});
