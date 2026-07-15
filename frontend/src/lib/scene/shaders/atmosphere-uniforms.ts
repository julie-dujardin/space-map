import { BackSide, FrontSide, Vector3 } from 'three';
import type { BodyObjects } from '$lib/scene/types';
import { SUN_ID } from '$lib/constants';

const spinAxis = new Vector3();

/**
 * Refresh per-frame shell state: `uSunDir`, the body's spin axis (world-space
 * pole for the shader's oblateness squash), and the material side — the shell
 * flips to BackSide when the camera enters it, so the sky keeps rendering from
 * inside the atmosphere.
 */
export function updateAtmosphereShaders(
	bodyObjects: Map<string, BodyObjects>,
	cameraPosition: Vector3,
	visible: boolean
): void {
	const sunPos = bodyObjects.get(SUN_ID)?.body.position;
	if (!sunPos) return;
	for (const bo of bodyObjects.values()) {
		if (!bo.atmosphere) continue;
		bo.atmosphere.mesh.visible = visible;
		if (!visible) continue;
		const [bx, by, bz] = bo.body.position;
		const uniforms = bo.atmosphere.material.uniforms;
		(uniforms.uSunDir.value as Vector3)
			.set(sunPos[0] - bx, sunPos[1] - by, sunPos[2] - bz)
			.normalize();
		// applyOrientation puts the pole on mesh-local +Y; the quaternion's spin
		// component is about that same axis, so the phase doesn't matter.
		if (bo.mesh) {
			spinAxis.set(0, 1, 0).applyQuaternion(bo.mesh.quaternion);
			(uniforms.uSpinAxis.value as Vector3).copy(spinAxis);
		}
		const atmoMesh = bo.atmosphere.mesh;
		const shellRadius = bo.atmosphere.geometryRadiusScene * atmoMesh.scale.x;
		const inside = cameraPosition.distanceToSquared(atmoMesh.position) < shellRadius * shellRadius;
		bo.atmosphere.material.side = inside ? BackSide : FrontSide;
	}
}
