import { Color, type MeshStandardMaterial } from 'three';
import type { BodyObjects } from '$lib/scene/types';
import { SUN_ID } from '$lib/constants';
import { SUN_LIGHT_INTENSITY, sunIrradianceFactor } from '$lib/scene/lighting';
import { meanMapColor } from '$lib/scene/objects/body/texture-tint';
import { MAX_OCCLUDERS } from '$lib/scene/objects/surface/eclipse-shadow';
import { selectShiners, type Shiner } from '$lib/scene/objects/surface/planetshine';

const _shiners: Shiner[] = Array.from({ length: MAX_OCCLUDERS }, () => ({
	x: 0,
	y: 0,
	z: 0,
	radius: 0,
	sunX: 0,
	sunY: 0,
	sunZ: 0,
	sunlight: 0,
	albedo: new Color()
}));

/**
 * Fill the planetshine uniforms of each receiver for the frame. The shiners
 * are the `occluders` of the eclipse pass that draw a mesh. A shiner has the
 * colour the scene draws it with, and the sunlight of the direct light at its
 * own distance from the Sun.
 */
export function updatePlanetshineUniforms(
	bodyObjects: Map<string, BodyObjects>,
	occluders: readonly BodyObjects[],
	realistic: boolean,
	sunScale: number
): void {
	const sunPos = bodyObjects.get(SUN_ID)?.body.position;
	let n = 0;
	if (sunPos) {
		for (const bo of occluders) {
			if (!bo.mesh) continue;
			const material = bo.mesh.material as MeshStandardMaterial;
			const [x, y, z] = bo.body.position!;
			const sx = sunPos[0] - x;
			const sy = sunPos[1] - y;
			const sz = sunPos[2] - z;
			const sunDist = Math.hypot(sx, sy, sz);
			const s = _shiners[n++];
			s.x = x;
			s.y = y;
			s.z = z;
			s.radius = bo.radiusScene;
			s.sunX = sx / sunDist;
			s.sunY = sy / sunDist;
			s.sunZ = sz / sunDist;
			s.sunlight = SUN_LIGHT_INTENSITY * sunScale * (realistic ? sunIrradianceFactor(sunDist) : 1);
			s.albedo.copy(material.color);
			const mean = material.map && meanMapColor(material.map);
			if (mean) s.albedo.multiply(mean);
		}
	}

	for (const bo of bodyObjects.values()) {
		const shine = bo.planetshine;
		const at = bo.body.position;
		if (!shine || !at) continue;
		// A body this small draws no fragments. The eclipse pass skips it too.
		if (bo.cachedDist > 0 && bo.radiusScene < bo.cachedDist * 1e-4) continue;
		selectShiners(shine, at[0], at[1], at[2], _shiners, n);
	}
}
