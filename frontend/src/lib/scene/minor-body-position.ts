import type { PositionedBody } from '$lib/types/objects';
import { orbitalElementsToPositionJD, parabolicToPositionJD } from '$lib/math/orbit/position';
import type { ContextManager } from '$lib/scene/context-manager.svelte';

/**
 * Recompute `body.position` in place from its orbital elements at `jd`.
 * Point-cloud bodies (asteroids, spacecraft) aren't in `ctx.bodiesById`, so
 * the per-frame `updatePositions` loop skips them — their visible dots are
 * advanced on the GPU by the orbit pool, and the CPU copy stays frozen at
 * load. Call this at pick / promotion time so `body.position` matches the
 * rendered dot.
 */
export function refreshMinorBodyPosition(
	body: PositionedBody,
	jd: number,
	ctx: ContextManager
): void {
	const d = body.data;
	const isParabolic = d.q != null;
	if (d.a === 0 && !isParabolic) return; // coincides with parent — nothing to propagate
	const offset = isParabolic ? parabolicToPositionJD(d, jd) : orbitalElementsToPositionJD(d, jd);
	if (!offset) return;
	const parentPos = ctx.getBody(d.parentId)?.position ?? [0, 0, 0];
	body.position[0] = parentPos[0] + offset[0];
	body.position[1] = parentPos[1] + offset[1];
	body.position[2] = parentPos[2] + offset[2];
	if (body.orbitCenter) {
		body.orbitCenter[0] = parentPos[0];
		body.orbitCenter[1] = parentPos[1];
		body.orbitCenter[2] = parentPos[2];
	}
}
