import { Vector3 } from 'three';
import type { Vec3 } from '$lib/scene/animation/math';
import type { BodyObjects } from '$lib/scene/types';
import { SUN_ID } from '$lib/constants';

/** Refresh per-frame ring + planet-ring-shadow uniforms (sun dir, planet center, pole). */
export function updateRingShaders(bodyObjects: Map<string, BodyObjects>, focusTruePos: Vec3): void {
	const sunPos = bodyObjects.get(SUN_ID)?.body.position;
	if (!sunPos) return;
	const [fx, fy, fz] = focusTruePos;
	for (const bo of bodyObjects.values()) {
		if (!bo.rings) continue;
		const [bx, by, bz] = bo.body.position;

		// Body → sun direction (the focus offset cancels, so world == scene-rel).
		const ringSunDir = bo.rings.material.uniforms.uSunDir.value as Vector3;
		ringSunDir.set(sunPos[0] - bx, sunPos[1] - by, sunPos[2] - bz).normalize();

		// Shared by both ray-marches: planet-shadow-on-ring (always present)
		// and ring-shadow-on-planet (present once attachRingShadowToPlanet runs).
		const psOnRing = bo.rings.planetShadowOnRing;
		psOnRing.uPlanetCenter.value.set(bx - fx, by - fy, bz - fz);
		if (bo.mesh) {
			psOnRing.uPlanetPoleDir.value.set(0, 1, 0).applyQuaternion(bo.mesh.quaternion);
		}

		const ps = bo.rings.planetShadow;
		if (!ps) continue;
		ps.uRingShadowSunDir.value.copy(ringSunDir);
		ps.uRingShadowPoleDir.value.copy(psOnRing.uPlanetPoleDir.value);
		ps.uRingShadowCenter.value.copy(psOnRing.uPlanetCenter.value);
	}
}
