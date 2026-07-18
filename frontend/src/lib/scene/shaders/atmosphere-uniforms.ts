import { BackSide, FrontSide, Vector3 } from 'three';
import type { BodyObjects } from '$lib/scene/types';
import { SUN_ID } from '$lib/constants';
import { sunIrradianceFactor } from '$lib/scene/lighting';

const spinAxis = new Vector3();

/**
 * Refresh per-frame shell state: `uSunDir`, the body's spin axis (world-space
 * pole for the shader's oblateness squash), and the material side — the shell
 * flips to BackSide when the camera enters it, so the sky keeps rendering from
 * inside the atmosphere. `realistic` scales the tuned sun intensity by the
 * body's inverse-square distance from the Sun (bodies flagged
 * `realisticSunAlways` get that scaling in every mode); `sunScale` is the
 * debug lighting-tuner multiplier shared with the scene's sun lights.
 *
 * Returns whether any shell now has the camera inside it — the renderer uses
 * that to decide whether to run the opaque-depth prepass those shells sample.
 */
export function updateAtmosphereShaders(
	bodyObjects: Map<string, BodyObjects>,
	cameraPosition: Vector3,
	visible: boolean,
	realistic: boolean,
	sunScale: number
): boolean {
	const sunPos = bodyObjects.get(SUN_ID)?.body.position;
	if (!sunPos) return false;
	let anyInside = false;
	for (const bo of bodyObjects.values()) {
		if (!bo.atmosphere) continue;
		bo.atmosphere.mesh.visible = visible;
		if (!visible) continue;
		const [bx, by, bz] = bo.body.position;
		const uniforms = bo.atmosphere.material.uniforms;
		const sunVec = (uniforms.uSunDir.value as Vector3).set(
			sunPos[0] - bx,
			sunPos[1] - by,
			sunPos[2] - bz
		);
		const params = bo.atmosphere.params;
		uniforms.uSunIntensity.value =
			params.sunIntensity *
			(realistic || params.realisticSunAlways ? sunIrradianceFactor(sunVec.length()) : 1) *
			sunScale;
		sunVec.normalize();
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
		// From inside, the visible shell fragment is the far hemisphere — writing
		// its depth would cull the point clouds/trails beyond the night sky, and
		// depth-testing it against the nearer terrain would reject the very
		// fragments that carry the camera→ground aerial perspective. So depth
		// test/write are off; instead the shader samples the opaque-depth prepass
		// (uUseDepth) to stop its march at real terrain.
		bo.atmosphere.material.depthWrite = !inside;
		bo.atmosphere.material.depthTest = !inside;
		bo.atmosphere.material.uniforms.uUseDepth.value = inside ? 1 : 0;
		if (inside) anyInside = true;
	}
	return anyInside;
}
