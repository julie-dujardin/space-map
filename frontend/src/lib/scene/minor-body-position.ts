import { ObjectType, isSurfaceFeature, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { orbitalElementsToPositionJD, parabolicToPositionJD } from '$lib/math/orbit/position';
import { sgp4PositionScene } from '$lib/math/orbit/sgp4';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { SSB_ID } from '$lib/constants';
import { J2000_JD } from '$lib/time/jd';

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
	body.placedJd = jd;
	const isParabolic = d.q != null;
	// Only the SSB is the scene origin — the Sun wobbles ~1e6 km around the
	// barycenter. Any other parent must be loaded; leave the body unplaced
	// rather than anchor it at the origin. Mirrors update-positions.
	let parentPos: readonly [number, number, number];
	if (d.parentId === SSB_ID) {
		parentPos = [0, 0, 0];
	} else {
		const resolved = ctx.getBody(d.parentId)?.position;
		if (!resolved) {
			body.positionUnknown = true;
			return;
		}
		parentPos = resolved;
	}
	// Outside chunk validity there is nothing to propagate — avoid SGP4 divergence.
	if (jd < d.validityStart || jd > d.validityEnd) {
		body.positionUnknown = true;
		return;
	}
	const coincidesWithParent = d.a === 0 && !isParabolic && !d.satrec;
	const offset = coincidesWithParent
		? ([0, 0, 0] as [number, number, number])
		: d.satrec
			? sgp4PositionScene(d.satrec, jd)
			: isParabolic
				? parabolicToPositionJD(d, jd)
				: orbitalElementsToPositionJD(d, jd);
	if (!offset) {
		body.positionUnknown = true;
		return;
	}
	body.position[0] = parentPos[0] + offset[0];
	body.position[1] = parentPos[1] + offset[1];
	body.position[2] = parentPos[2] + offset[2];
	if (body.orbitCenter) {
		body.orbitCenter[0] = parentPos[0];
		body.orbitCenter[1] = parentPos[1];
		body.orbitCenter[2] = parentPos[2];
	}
	body.positionUnknown = false;
}

/**
 * Recompute a moon's `position` in place. The frame loop leaves a moon outside
 * the focused system where it last placed it, so call this to read one at
 * `jd`. Same gates as update-positions: a moon that loop would hide is left a
 * stand-in.
 */
export function refreshMoonPosition(body: PositionedBody, jd: number, ctx: ContextManager): void {
	const d = body.data;
	body.placedJd = jd;
	body.positionUnknown = true;
	if (d.unplaceable) return;
	if (d.visibleFromDays !== undefined && jd - J2000_JD < d.visibleFromDays) return;
	const parent = ctx.getBody(d.parentId);
	if (!parent || !placeForRead(parent, jd, ctx)) return;
	const parentPos = parent.position;
	// Chebyshev has no Kepler fallback: an extrapolated place is a wrong one.
	const offset = ctx.chebStore?.has(d.id)
		? ctx.chebStore.positionScene(d.id, jd)
		: d.a === 0
			? ([0, 0, 0] as const)
			: orbitalElementsToPositionJD(d, jd);
	if (!offset) return;
	body.position[0] = parentPos[0] + offset[0];
	body.position[1] = parentPos[1] + offset[1];
	body.position[2] = parentPos[2] + offset[2];
	if (body.orbitCenter) {
		body.orbitCenter[0] = parentPos[0];
		body.orbitCenter[1] = parentPos[1];
		body.orbitCenter[2] = parentPos[2];
	}
	body.positionUnknown = false;
}

/** How long a probe stays placed on every frame after a host last read it. */
export const HOST_READ_MS = 2000;

/**
 * Settle `body.position` for `jd` where the frame loop did not: it skips a
 * moon outside the focused system, a dot of a point cloud and a hidden probe.
 * False while the body is nowhere at `jd`.
 */
export function placeForRead(body: PositionedBody, jd: number, ctx: ContextManager): boolean {
	const d = body.data;
	const stale = body.placedJd !== jd;
	if (d.orbitalSource === OrbitalSource.SPICE_PROBE) {
		const { hostRead } = ctx.bodies;
		if (!stale && !hostRead.has(d.id)) return !body.positionUnknown;
		if (!hostRead.has(d.id)) ctx.bodies.hostReadVersion++;
		hostRead.set(d.id, performance.now());
		// A probe has no orbit to place it from: the frame loop is asked to, and
		// until it has, where the probe was left is not where it is.
		if (stale) return false;
	} else if (stale) {
		if (d.objectType === ObjectType.MOON) refreshMoonPosition(body, jd, ctx);
		else if (!ctx.bodies.bodiesById.has(d.id) && !isSurfaceFeature(body)) {
			refreshMinorBodyPosition(body, jd, ctx);
		}
	}
	return !body.positionUnknown;
}
