import type { PerspectiveCamera, Vector2, Vector3 } from 'three';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { extrasolarIdOf } from '$lib/fetch/extrasolar/ids';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { ndcZVisible } from '$lib/scene/setup/depth-mode';
import { VISIBILITY } from '$lib/scene/visibility/thresholds';
import type { Vec3 } from '../animation/math';

/** A finger or a pen, which covers more of the screen than a cursor. */
export function isCoarsePointer(pointerType: string): boolean {
	return pointerType === 'touch' || pointerType === 'pen';
}

/** How far (CSS px) from the pointer a pick looks for a dot. */
export function pickRadiusPx(pointerType: string): number {
	return isCoarsePointer(pointerType) ? 48 : 24;
}

/** A body picked as a dot on screen. */
export interface DotHit {
	body: PositionedBody;
	/** Scene-unit distance from the camera. */
	distance: number;
	/** CSS-px distance from the cursor. */
	screenDist: number;
}

/** Where a dot pick looks, and how it tells a dot it may not take. */
export interface DotPick {
	pointer: Vector2;
	camera: PerspectiveCamera;
	ctx: ContextManager;
	focusTruePos: Vec3;
	canvasWidth: number;
	canvasHeight: number;
	tmpV3: Vector3;
	jd: number;
	pointerType: string;
	/** Returns false for a candidate hidden behind a mesh, so the nearest
	 *  *visible* dot wins instead of the nearest dot. Args are the dot's NDC and
	 *  its scene-unit distance from the camera. */
	isVisible?: (ndcX: number, ndcY: number, worldDist: number) => boolean;
}

/** Find the closest visible moon dot to the given pointer (NDC). Asteroids and
 *  spacecraft — the ~1.3M-dot clouds — are picked on the GPU (see
 *  {@link GpuPickPass}); only the few hundred moons are cheap enough to scan
 *  exactly on the CPU, so they stay here. */
export function pickMoonDot(pick: DotPick): DotHit | null {
	const { ctx } = pick;
	return pickDot(
		ctx.bodies.majorBodies.filter(
			(body) =>
				body.data.objectType === ObjectType.MOON &&
				ctx.visibility.isMoonGroupVisible(body.data.parentId)
		),
		pick
	);
}

/** The planets of other stars and their host stars, in the systems that
 *  draw. The nearest to the pointer wins, so a host stays clickable among
 *  its planets. */
export function pickSystemDot(pick: DotPick): DotHit | null {
	const { ctx } = pick;
	const bodies: PositionedBody[] = [];
	for (const hostId of ctx.visibility.systemShares.keys()) {
		const host = ctx.getBody(hostId);
		if (host && ctx.visibility.starShare > 0) bodies.push(host);
		const id = extrasolarIdOf(hostId);
		const planets = id === null ? undefined : ctx.exoplanets.held(id)?.planets.get(id);
		for (const planet of planets ?? []) {
			if (ctx.visibility.exoplanetShare(planet) > 0) bodies.push(planet);
		}
	}
	return bodies.length > 0 ? pickDot(bodies, pick) : null;
}

/** The Sun and the planets as dots, where they draw. The stars draw behind
 *  them, so a click by one of them is its own and not a star's. */
export function pickPlanetDot(pick: DotPick): DotHit | null {
	const { ctx, camera, focusTruePos } = pick;
	const [fx, fy, fz] = focusTruePos;
	const cam = camera.position;
	return pickDot(
		ctx.bodies.majorBodies.filter((body) => {
			const t = body.data.objectType;
			if (t !== ObjectType.STAR && t !== ObjectType.PLANET && t !== ObjectType.DWARF_PLANET) {
				return false;
			}
			const at = body.position;
			if (!at) return false;
			const dist = Math.hypot(at[0] - fx - cam.x, at[1] - fy - cam.y, at[2] - fz - cam.z);
			return ctx.visibility.getPlanetVisibility(body, dist) !== VISIBILITY.HIDE;
		}),
		pick
	);
}

function pickDot(bodies: readonly PositionedBody[], pick: DotPick): DotHit | null {
	const { pointer, camera, ctx, canvasWidth, canvasHeight, jd, isVisible } = pick;
	// Convert NDC pointer to pixel coords
	const px = (pointer.x + 1) * 0.5 * canvasWidth;
	const py = (1 - pointer.y) * 0.5 * canvasHeight;

	const v = pick.tmpV3;
	const [fx, fy, fz] = pick.focusTruePos;
	const cam = camera.position;
	let bestBody: PositionedBody | undefined;
	let bestScreenDist = pickRadiusPx(pick.pointerType);
	let bestWorldDist = Infinity;

	for (const body of bodies) {
		// The frame loop does not place a moon outside the focused system: settle
		// it at the current jd, so the pick matches the dot. A moon with no place
		// has no dot to pick.
		const at = ctx.place(body, jd);
		if (!at) continue;
		// Render-space position (focus sits at the scene origin, so subtracting
		// focusTruePos puts the body in the same frame as `camera.position`).
		v.set(at[0] - fx, at[1] - fy, at[2] - fz);
		// True scene-unit distance from camera — captured *before* project()
		// turns `v` into NDC coords. The caller compares this against the mesh
		// raycaster's `hits[0].distance` (also scene units) to pick whichever
		// is closer to the camera; using NDC magnitude here would always lose
		// to nearby mesh hits and hide point clouds in front of meshes.
		const worldDist = Math.hypot(v.x - cam.x, v.y - cam.y, v.z - cam.z);
		v.project(camera);
		// project() flips signs for points behind the camera (negative w),
		// pushing NDC z outside the visible depth range.
		if (!ndcZVisible(v.z)) continue;
		const sx = (v.x + 1) * 0.5 * canvasWidth;
		const sy = (1 - v.y) * 0.5 * canvasHeight;
		const screenDist = Math.hypot(sx - px, sy - py);
		const better =
			screenDist < bestScreenDist || (screenDist === bestScreenDist && worldDist < bestWorldDist);
		if (!better) continue;
		// Reject dots occluded by a mesh so the nearest visible dot wins — a dot
		// hidden behind a planet must not shadow the one the user can see.
		if (isVisible && !isVisible(v.x, v.y, worldDist)) continue;
		bestScreenDist = screenDist;
		bestWorldDist = worldDist;
		bestBody = body;
	}

	if (!bestBody) return null;
	return { body: bestBody, distance: bestWorldDist, screenDist: bestScreenDist };
}
