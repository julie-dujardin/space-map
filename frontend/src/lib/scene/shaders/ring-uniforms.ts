import { Vector3 } from 'three';
import type { Vec3 } from '$lib/scene/animation/math';
import type { BodyObjects } from '$lib/scene/types';

/**
 * Refresh per-frame ring uniforms — both the ring material's lit/unlit
 * sun direction, and the planet material's analytical ring-shadow inputs
 * (sun direction, pole direction, planet center). The shadow ray-march
 * runs entirely in world space, so all three vectors need updating as the
 * body orbits, spins, and the focus basis shifts.
 */
export function updateRingShaders(bodyObjects: Map<string, BodyObjects>, focusTruePos: Vec3): void {
	const sunPos = bodyObjects.get('naif-10')?.body.position;
	if (!sunPos) return;
	const [fx, fy, fz] = focusTruePos;
	for (const bo of bodyObjects.values()) {
		if (!bo.rings) continue;
		const [bx, by, bz] = bo.body.position;

		// uSunDir on the ring material — direction body → sun in true
		// world coords. Same in scene/focus-relative coords because the
		// focus offset cancels.
		const ringSunDir = bo.rings.material.uniforms.uSunDir.value as Vector3;
		ringSunDir.set(sunPos[0] - bx, sunPos[1] - by, sunPos[2] - bz).normalize();

		// Planet center and pole are shared across both ray-marches:
		// the ring's planet-shadow path (`planetShadowOnRing`, always
		// present) and the planet's ring-shadow path (`planetShadow`,
		// present once `attachRingShadowToPlanet` has run).
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
