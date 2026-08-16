import type { PositionedBody } from '$lib/types/objects';
import { orbitalElementsToPositionJD, parabolicToPositionJD } from '$lib/math/orbit/position';
import { sgp4PositionScene } from '$lib/math/orbit/sgp4';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { SSB_ID } from '$lib/constants';

/**
 * Recompute `body.position` in place. Point-cloud bodies advance on the GPU
 * and their CPU copy stays frozen at load, so call this at pick/promotion
 * time to sync it to the rendered dot.
 *
 * SGP4-backed bodies use the same propagator as their orbit curve — a Kepler
 * fallback would drift a few km off the curve endpoint, which
 * `buildOrbitTrailPoints` misreads as mid-curve and freezes the trail.
 */
export function refreshMinorBodyPosition(
	body: PositionedBody,
	jd: number,
	ctx: ContextManager
): void {
	const d = body.data;
	const isParabolic = d.q != null;
	if (d.a === 0 && !isParabolic && !d.satrec) return; // coincides with parent — nothing to propagate
	if (jd < d.validityStart || jd > d.validityEnd) return; // outside chunk validity — avoid SGP4 divergence
	const offset = d.satrec
		? sgp4PositionScene(d.satrec, jd)
		: isParabolic
			? parabolicToPositionJD(d, jd)
			: orbitalElementsToPositionJD(d, jd);
	if (!offset) return;
	// Only the SSB is the scene origin — the Sun wobbles ~1e6 km around the
	// barycenter. Any other parent must be loaded; hide rather than anchor at
	// the origin. Mirrors update-positions.
	let parentPos: readonly [number, number, number];
	if (d.parentId === SSB_ID) {
		parentPos = [0, 0, 0];
	} else {
		const resolved = ctx.getBody(d.parentId)?.position;
		if (!resolved) return;
		parentPos = resolved;
	}
	body.position[0] = parentPos[0] + offset[0];
	body.position[1] = parentPos[1] + offset[1];
	body.position[2] = parentPos[2] + offset[2];
	if (body.orbitCenter) {
		body.orbitCenter[0] = parentPos[0];
		body.orbitCenter[1] = parentPos[1];
		body.orbitCenter[2] = parentPos[2];
	}
}
