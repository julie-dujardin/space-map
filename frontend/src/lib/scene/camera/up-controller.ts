import { Quaternion, Vector3, type PerspectiveCamera } from 'three';
import type { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { angularDuration, UP_PACING } from '$lib/scene/animation/pacing';
import { SCENE_UP, bodyNorthVector, galacticNorthVector, GALACTIC_REF_ID } from './north-reference';

/**
 * Drives `camera.up` from a north reference, slerping across switches so the
 * scene doesn't snap. Also re-pokes `OrbitControls`'s cached up→Y quat —
 * without that, dragging after a switch rotates around the wrong axis.
 */
export class CameraUpController {
	private refId: string | null = null;
	private readonly startVec = new Vector3(0, 1, 0);
	private readonly targetVec = new Vector3(0, 1, 0);
	private readonly currentVec = new Vector3(0, 1, 0);
	private animStartTime = -Infinity;
	private animDurationMs = UP_PACING.refMs;
	/** True between `setNorthReference` and the next `update()` — defers the
	 *  duration calc until we have `jd` to compute the target pole. */
	private needsDurationCalc = false;
	private readonly _quatA = new Quaternion();
	private readonly _quatB = new Quaternion();

	constructor(
		private readonly camera: PerspectiveCamera,
		private readonly controls: OrbitControls,
		private readonly ctx: ContextManager,
		/** Landed probes get zenith as north instead of the static model up. */
		private readonly isLanded: (id: string) => boolean
	) {}

	/** `null` reverts to ecliptic Y; any other id triggers a slerp to its pole. */
	setNorthReference(id: string | null): void {
		if (id === this.refId) return;
		this.refId = id;
		this.startVec.copy(this.currentVec);
		this.animStartTime = performance.now();
		this.needsDurationCalc = true;
	}

	update(jd: number): void {
		if (this.refId === GALACTIC_REF_ID) {
			galacticNorthVector(this.targetVec);
		} else {
			const refBody = this.refId ? this.ctx.getBody(this.refId) : undefined;
			if (refBody) {
				// Feature has no orientation; `orbitCenter` (host centre) makes the
				// landed path yield local zenith.
				const landed = !!refBody.featureAnchor || this.isLanded(refBody.data.id);
				bodyNorthVector(refBody, jd, this.targetVec, landed);
			} else {
				this.targetVec.copy(SCENE_UP);
			}
		}

		if (this.needsDurationCalc) {
			this.needsDurationCalc = false;
			const angle = this.startVec.angleTo(this.targetVec);
			this.animDurationMs = angularDuration(angle, UP_PACING);
		}

		const elapsed = performance.now() - this.animStartTime;
		if (elapsed >= this.animDurationMs) {
			this.currentVec.copy(this.targetVec);
		} else {
			const t = Math.max(0, elapsed / this.animDurationMs);
			const s = t * t * (3 - 2 * t);
			// Slerp via the rotation quaternions that map ecliptic Y → start/target.
			this._quatA.setFromUnitVectors(SCENE_UP, this.startVec);
			this._quatB.setFromUnitVectors(SCENE_UP, this.targetVec);
			this._quatA.slerp(this._quatB, s);
			this.currentVec.copy(SCENE_UP).applyQuaternion(this._quatA);
		}
		this.camera.up.copy(this.currentVec);

		// OrbitControls caches its up→Y quat at construction and never refreshes it.
		const ctrls = this.controls as unknown as { _quat: Quaternion; _quatInverse: Quaternion };
		ctrls._quat.setFromUnitVectors(this.currentVec, SCENE_UP);
		ctrls._quatInverse.copy(ctrls._quat).invert();
	}
}
