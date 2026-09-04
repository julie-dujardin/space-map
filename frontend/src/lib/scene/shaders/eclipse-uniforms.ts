import type { Vec3 } from '$lib/scene/animation/math';
import type { BodyObjects } from '$lib/scene/types';
import { ObjectType } from '$lib/types/objects';
import {
	cullOccludersFor,
	getEclipseSceneUniforms,
	MAX_OCCLUDERS
} from '$lib/scene/objects/surface/eclipse-shadow';
import { SUN_ID } from '$lib/constants';

// Reused across frames; trimmed to active prefix each call.
const _candidatesScratch: BodyObjects[] = [];

/** Refresh per-frame eclipse uniforms (sun, occluders, self-pos). Occluders
 *  need a measured `radiusKm`; stars excluded since the Sun *is* the light.
 *  On overflow keeps the largest {@link MAX_OCCLUDERS} by scene radius. */
export function updateEclipseUniforms(
	bodyObjects: Map<string, BodyObjects>,
	focusTruePos: Vec3
): void {
	const eclipse = getEclipseSceneUniforms();
	const sunBo = bodyObjects.get(SUN_ID);
	if (!sunBo) {
		eclipse.uSunAngularRadius.value = 0;
		eclipse.uOccluderCount.value = 0;
		return;
	}
	const [fx, fy, fz] = focusTruePos;
	const sunPos = sunBo.body.position;
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

	const candidates = _candidatesScratch;
	let n = 0;
	for (const bo of bodyObjects.values()) {
		if (bo.body.data.objectType === ObjectType.STAR) continue;
		const km = bo.body.data.radiusKm;
		if (!Number.isFinite(km) || km <= 0) continue;
		if (bo.radiusScene <= 0) continue;
		candidates[n++] = bo;
	}
	candidates.length = n;
	if (n > MAX_OCCLUDERS) {
		candidates.sort((a, b) => b.radiusScene - a.radiusScene);
		candidates.length = MAX_OCCLUDERS;
		n = MAX_OCCLUDERS;
	}
	const slots = eclipse.uOccluders.value;
	for (let i = 0; i < n; i++) {
		const bo = candidates[i];
		const [bx, by, bz] = bo.body.position;
		slots[i].set(bx - fx, by - fy, bz - fz, bo.radiusScene);
	}
	eclipse.uOccluderCount.value = n;
	// Drop refs so the scratch doesn't pin disposed BodyObjects (they
	// transitively hold DOM elements and GPU resources).
	for (let i = 0; i < n; i++) candidates[i] = undefined as never;
	candidates.length = 0;

	// Each receiver gets its centre and the occluders that can reach it. A
	// receiver too small to render keeps its last list: its fragments are
	// never shaded, and the list is rebuilt the frame it grows back.
	const sunDir = eclipse.uSunDir.value;
	for (const bo of bodyObjects.values()) {
		const self = bo.eclipseShadow;
		if (!self) continue;
		if (bo.cachedDist > 0 && bo.radiusScene < bo.cachedDist * 1e-4) continue;
		const [bx, by, bz] = bo.body.position;
		const center = self.uEclipseSelfPos.value.set(bx - fx, by - fy, bz - fz);
		self.uOccluderCount.value = cullOccludersFor(
			self.uOccluders.value,
			center,
			bo.radiusScene,
			sunDir
		);
	}
}
