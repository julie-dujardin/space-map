import { Vector3 } from 'three';
import type { Vec3 } from '$lib/scene/animation/math';
import type { BodyObjects } from '$lib/scene/types';
import { SUN_ID } from '$lib/constants';
import { sunIrradianceFactor } from '$lib/scene/lighting';
import { kmToScene } from '$lib/math/units';

// IAU nominal solar radius; over the ring-planet distance this gives the
// sun's angular radius, which sets the penumbra widths of both ring-shadow
// ray-marches.
const SUN_RADIUS_SCENE = kmToScene(695_700);

/**
 * Refresh per-frame ring + planet-ring-shadow uniforms (sun dir, planet center,
 * pole). `realistic` scales the pre-lit ring albedo by inverse-square distance
 * from the Sun, since scene lights never touch the ring ShaderMaterial.
 * `overexpose` renders the stored (peak-normalised) channel values unscaled
 * instead of × intensity_scale, lifting faint systems to full visibility.
 */
export function updateRingShaders(
	bodyObjects: Map<string, BodyObjects>,
	focusTruePos: Vec3,
	realistic: boolean,
	overexpose: boolean
): void {
	const sunPos = bodyObjects.get(SUN_ID)?.body.position;
	if (!sunPos) return;
	const [fx, fy, fz] = focusTruePos;
	for (const bo of bodyObjects.values()) {
		if (!bo.rings) continue;
		const [bx, by, bz] = bo.body.position;

		const intensity = overexpose ? 1 : bo.rings.intensityScale;
		bo.rings.material.uniforms.uIntensityScale.value = intensity;

		// Body → sun direction (the focus offset cancels, so world == scene-rel).
		const ringSunDir = bo.rings.material.uniforms.uSunDir.value as Vector3;
		ringSunDir.set(sunPos[0] - bx, sunPos[1] - by, sunPos[2] - bz);
		const sunDist = ringSunDir.length();
		const sunAngularRadius = SUN_RADIUS_SCENE / sunDist;
		bo.rings.material.uniforms.uSunAngularRadius.value = sunAngularRadius;
		bo.rings.material.uniforms.uLightScale.value = realistic ? sunIrradianceFactor(sunDist) : 1;
		ringSunDir.normalize();

		// Shared by both ray-marches: planet-shadow-on-ring (always present)
		// and ring-shadow-on-planet (present once attachRingShadowToPlanet runs).
		const psOnRing = bo.rings.planetShadowOnRing;
		psOnRing.uPlanetCenter.value.set(bx - fx, by - fy, bz - fz);
		if (bo.mesh) {
			psOnRing.uPlanetPoleDir.value.set(0, 1, 0).applyQuaternion(bo.mesh.quaternion);
		}

		const ps = bo.rings.planetShadow;
		if (!ps) continue;
		// Shared refs with the atmosphere shell's ring-shadow uniforms.
		ps.uRingShadowIntensity.value = intensity;
		ps.uRingShadowSunAngularRadius.value = sunAngularRadius;
		ps.uRingShadowSunDir.value.copy(ringSunDir);
		ps.uRingShadowPoleDir.value.copy(psOnRing.uPlanetPoleDir.value);
		ps.uRingShadowCenter.value.copy(psOnRing.uPlanetCenter.value);
	}
}
