import type { Vec3 } from '$lib/scene/animation/math';
import type { BodyObjects } from '$lib/scene/types';
import { ObjectType } from '$lib/types/objects';
import { getEclipseSceneUniforms, MAX_OCCLUDERS } from '$lib/scene/objects/eclipse-shadow';

// Reused across frames; trimmed to active prefix each call. Module-scope is
// fine because there's exactly one consumer (updateEclipseUniforms) and it
// runs synchronously inside tick().
const _candidatesScratch: BodyObjects[] = [];

/**
 * Refresh per-frame eclipse uniforms — sun position/radius, the
 * occluder list, and each receiver's self-position. Occluder
 * eligibility is gated on a measured (real) `radiusKm`: the data layer
 * fills in a fallback radius for bodies whose physical size is
 * unknown, and using those for shadow casting would draw wrong-sized
 * shadows. Stars are excluded since the Sun *is* the light source.
 *
 * If the system has more than {@link MAX_OCCLUDERS} eligible bodies we
 * keep the largest by scene radius — those dominate the shadow budget
 * and the smaller ones contribute negligible obscuration anyway.
 */
export function updateEclipseUniforms(
	bodyObjects: Map<string, BodyObjects>,
	focusTruePos: Vec3
): void {
	const eclipse = getEclipseSceneUniforms();
	const sunBo = bodyObjects.get('naif-10');
	if (!sunBo) {
		eclipse.uSunAngularRadius.value = 0;
		eclipse.uOccluderCount.value = 0;
		return;
	}
	const [fx, fy, fz] = focusTruePos;
	const sunPos = sunBo.body.position;
	// Sun→focus vector is huge in scene units (~1 AU), so do the
	// magnitude work here in float64 and ship the shader a unit
	// direction + a precomputed angular radius. Variation in either
	// across a body is ~r/AU ≈ 1e-5, well below the Sun's own
	// angular size, so per-fragment recomputation in float32 would
	// just inject quantisation banding for no physical gain.
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

	// Collect eligible occluders (non-star bodies with a measured
	// radius) and sort by scene radius descending so that if there are
	// more than MAX_OCCLUDERS we keep the dominant ones.
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
	// Drop refs so the pool doesn't pin removed bodies' meshes/materials
	// (BodyObjects transitively references DOM elements and GPU resources).
	for (let i = 0; i < n; i++) candidates[i] = undefined as never;
	candidates.length = 0;

	// Receivers: every non-star body that got an eclipse handler at
	// construction time. Mirror its focus-relative center so the
	// shader can skip its own slot in the occluder loop.
	for (const bo of bodyObjects.values()) {
		if (!bo.eclipseShadow) continue;
		const [bx, by, bz] = bo.body.position;
		bo.eclipseShadow.uEclipseSelfPos.value.set(bx - fx, by - fy, bz - fz);
	}
}
