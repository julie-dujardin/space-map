import { Vector3, Vector4 } from 'three';
import type { Vec3 } from '$lib/scene/animation/math';
import { isDrawn, type BodyObjects } from '$lib/scene/types';
import { ObjectType } from '$lib/types/objects';
import {
	atmosphereLeak,
	cullOccludersFor,
	getEclipseSceneUniforms,
	getOccluderPool
} from '$lib/scene/objects/surface/eclipse-shadow';
import { SUN_ID } from '$lib/constants';

const FOCUS = new Vector3();

/** Put the occluders of the frame in `out` and return it. An occluder is
 *  drawn, has a measured `radiusKm` and is not a star. The caller must clear
 *  `out` after use, so it does not keep disposed bodies alive. */
export function collectOccluders(
	bodyObjects: Map<string, BodyObjects>,
	out: BodyObjects[]
): BodyObjects[] {
	let n = 0;
	for (const bo of bodyObjects.values()) {
		if (bo.body.data.objectType === ObjectType.STAR) continue;
		const km = bo.body.data.radiusKm;
		if (!Number.isFinite(km) || km <= 0) continue;
		// A body that is not drawn casts no shadow.
		if (bo.radiusScene <= 0 || !isDrawn(bo)) continue;
		out[n++] = bo;
	}
	out.length = n;
	return out;
}

/**
 * Fill the eclipse uniforms for the frame: the Sun, the occluder pool from
 * the `occluders` of {@link collectOccluders}, and the list of each receiver.
 * The scene set holds the occluders that can shadow the space within
 * `cameraDistance` of the focus. With `air` off, no occluder bends light into
 * its shadow.
 */
export function updateEclipseUniforms(
	bodyObjects: Map<string, BodyObjects>,
	occluders: readonly BodyObjects[],
	focusTruePos: Vec3,
	cameraDistance: number,
	air: boolean
): void {
	const eclipse = getEclipseSceneUniforms();
	const pool = getOccluderPool();
	const sunBo = bodyObjects.get(SUN_ID);
	const sunPos = sunBo?.body.position;
	if (!sunBo || !sunPos) {
		eclipse.uSunAngularRadius.value = 0;
		eclipse.uOccluderCount.value = 0;
		pool.count = 0;
		return;
	}
	const [fx, fy, fz] = focusTruePos;
	// Precompute unit-dir + angular radius in float64. Per-fragment recompute
	// in float32 over ~1 AU would just inject quantisation banding (variation
	// across a body is ~r/AU ≈ 1e-5, well below the Sun's angular size).
	const sx = sunPos[0] - fx;
	const sy = sunPos[1] - fy;
	const sz = sunPos[2] - fz;
	const sunDist = Math.hypot(sx, sy, sz);
	if (sunDist > 0) {
		eclipse.uSunDir.value.set(sx / sunDist, sy / sunDist, sz / sunDist);
		eclipse.uSunAngularRadius.value = Math.asin(Math.min(sunBo.radiusScene / sunDist, 1));
	} else {
		eclipse.uSunAngularRadius.value = 0;
	}

	const n = occluders.length;
	while (pool.occluders.length < n) {
		pool.occluders.push(new Vector4());
		pool.leaks.push(new Vector4());
	}
	for (let i = 0; i < n; i++) {
		const bo = occluders[i];
		const [bx, by, bz] = bo.body.position!;
		pool.occluders[i].set(bx - fx, by - fy, bz - fz, bo.radiusScene);
		if (air && bo.atmosphere) {
			atmosphereLeak(bo.atmosphere.params, bo.atmosphere.planetRadiusKm, pool.leaks[i]);
		} else {
			pool.leaks[i].set(0, 0, 0, 0);
		}
	}
	pool.count = n;

	const sunDir = eclipse.uSunDir.value;
	eclipse.uOccluderCount.value = cullOccludersFor(
		eclipse.uOccluders.value,
		FOCUS,
		cameraDistance,
		sunDir,
		eclipse.uOccluderLeak.value
	);

	// Each receiver gets its centre and the occluders that can reach it. A
	// receiver too small to render keeps its last list: its fragments are
	// never shaded, and the list is rebuilt the frame it grows back.
	for (const bo of bodyObjects.values()) {
		const self = bo.eclipseShadow;
		const at = bo.body.position;
		if (!self || !at) continue;
		if (bo.cachedDist > 0 && bo.radiusScene < bo.cachedDist * 1e-4) continue;
		const [bx, by, bz] = at;
		const center = self.uEclipseSelfPos.value.set(bx - fx, by - fy, bz - fz);
		self.uOccluderCount.value = cullOccludersFor(
			self.uOccluders.value,
			center,
			bo.radiusScene,
			sunDir,
			self.uOccluderLeak.value
		);
	}
}
