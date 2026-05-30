import { Vector3 } from 'three';
import type { BodyObjects } from '$lib/scene/types';
import { SUN_ID } from '$lib/constants';

/** Refresh per-frame `uSunDir` on every scattering shell. */
export function updateAtmosphereShaders(bodyObjects: Map<string, BodyObjects>): void {
	const sunPos = bodyObjects.get(SUN_ID)?.body.position;
	if (!sunPos) return;
	for (const bo of bodyObjects.values()) {
		if (!bo.atmosphere) continue;
		const [bx, by, bz] = bo.body.position;
		(bo.atmosphere.material.uniforms.uSunDir.value as Vector3)
			.set(sunPos[0] - bx, sunPos[1] - by, sunPos[2] - bz)
			.normalize();
	}
}
