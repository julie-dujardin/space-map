import { Vector3 } from 'three';
import type { BodyObjects } from '$lib/scene/types';

/**
 * Refresh per-frame atmosphere uniforms: the body→Sun direction for each
 * body that carries a scattering shell. Everything else the shader needs is
 * static (radii, coefficients) or derived from the shell mesh's model
 * matrix (the planet centre), so this is the only per-frame work.
 */
export function updateAtmosphereShaders(bodyObjects: Map<string, BodyObjects>): void {
	const sunPos = bodyObjects.get('naif-10')?.body.position;
	if (!sunPos) return;
	for (const bo of bodyObjects.values()) {
		if (!bo.atmosphere) continue;
		const [bx, by, bz] = bo.body.position;
		(bo.atmosphere.material.uniforms.uSunDir.value as Vector3)
			.set(sunPos[0] - bx, sunPos[1] - by, sunPos[2] - bz)
			.normalize();
	}
}
