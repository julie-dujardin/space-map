import { Quaternion, Vector3, type Scene } from 'three';
import { SKYBOX_BASE_ROTATION } from '$lib/scene/objects/skybox';

const DEG2RAD = Math.PI / 180;

/**
 * Debug-only adjustment applied on top of the math-derived skybox rotation.
 * Combined as `base · adjust(rxDeg, ryDeg, rzDeg)` so 0,0,0 reproduces the
 * derived alignment. Mutates `scene.backgroundRotation` on each call.
 */
export class SkyboxAdjuster {
	private readonly adjust = { rxDeg: 0, ryDeg: 0, rzDeg: 0 };
	private readonly _q = new Quaternion();
	private readonly _adjustQ = new Quaternion();
	private readonly _tmpQ = new Quaternion();
	private readonly _axisX = new Vector3(1, 0, 0);
	private readonly _axisY = new Vector3(0, 1, 0);
	private readonly _axisZ = new Vector3(0, 0, 1);

	constructor(private readonly scene: Scene) {}

	get(): { rxDeg: number; ryDeg: number; rzDeg: number } {
		return { ...this.adjust };
	}

	/**
	 * Apply an extra rotation on top of the math-derived skybox alignment.
	 * Angles are degrees, composed as Rz · Ry · Rx around the *scene* axes,
	 * then post-multiplied onto the base: `final = base · adjust`. Pass 0,0,0
	 * to clear and reproduce the analytically-derived rotation.
	 */
	set(rxDeg: number, ryDeg: number, rzDeg: number): void {
		this.adjust.rxDeg = rxDeg;
		this.adjust.ryDeg = ryDeg;
		this.adjust.rzDeg = rzDeg;
		this._adjustQ
			.setFromAxisAngle(this._axisX, rxDeg * DEG2RAD)
			.premultiply(this._tmpQ.setFromAxisAngle(this._axisY, ryDeg * DEG2RAD))
			.premultiply(this._tmpQ.setFromAxisAngle(this._axisZ, rzDeg * DEG2RAD));
		this._q.copy(SKYBOX_BASE_ROTATION).multiply(this._adjustQ);
		this.scene.backgroundRotation.setFromQuaternion(this._q);
	}
}
