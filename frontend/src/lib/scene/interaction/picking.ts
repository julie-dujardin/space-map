import type { PerspectiveCamera, Vector2, Vector3 } from 'three';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { refreshMinorBodyPosition } from '$lib/scene/minor-body-position';
import { ndcZVisible } from '$lib/scene/setup/depth-mode';
import type { Vec3 } from '../animation/math';

/** Find the closest visible moon dot to the given pointer (NDC). Asteroids and
 *  spacecraft — the ~1.3M-dot clouds — are picked on the GPU (see
 *  {@link GpuPickPass}); only the few hundred moons are cheap enough to scan
 *  exactly on the CPU, so they stay here. */
export function pickMoonDot(
	pointer: Vector2,
	camera: PerspectiveCamera,
	ctx: ContextManager,
	focusTruePos: Vec3,
	canvasWidth: number,
	canvasHeight: number,
	tmpV3: Vector3,
	jd: number,
	pointerType: string,
	/** Returns false for a candidate hidden behind a mesh, so the nearest
	 *  *visible* dot wins instead of the nearest dot. Args are the dot's NDC and
	 *  its scene-unit distance from the camera. */
	isVisible?: (ndcX: number, ndcY: number, worldDist: number) => boolean
): { body: PositionedBody; distance: number; screenDist: number } | null {
	const SCREEN_THRESHOLD = pointerType === 'touch' || pointerType === 'pen' ? 48 : 24;
	// Convert NDC pointer to pixel coords
	const px = (pointer.x + 1) * 0.5 * canvasWidth;
	const py = (1 - pointer.y) * 0.5 * canvasHeight;

	const v = tmpV3;
	const [fx, fy, fz] = focusTruePos;
	const cam = camera.position;
	let bestBody: PositionedBody | undefined;
	let bestScreenDist = SCREEN_THRESHOLD;
	let bestWorldDist = Infinity;

	const testBody = (body: PositionedBody): void => {
		// Moon dots' positions are advanced on the GPU; refresh the CPU copy from
		// orbital elements at the current jd so picking matches the rendered dot
		// even while paused.
		refreshMinorBodyPosition(body, jd, ctx);
		// Render-space position (focus sits at the scene origin, so subtracting
		// focusTruePos puts the body in the same frame as `camera.position`).
		v.set(body.position[0] - fx, body.position[1] - fy, body.position[2] - fz);
		// True scene-unit distance from camera — captured *before* project()
		// turns `v` into NDC coords. The caller compares this against the mesh
		// raycaster's `hits[0].distance` (also scene units) to pick whichever
		// is closer to the camera; using NDC magnitude here would always lose
		// to nearby mesh hits and hide point clouds in front of meshes.
		const worldDist = Math.hypot(v.x - cam.x, v.y - cam.y, v.z - cam.z);
		v.project(camera);
		// project() flips signs for points behind the camera (negative w),
		// pushing NDC z outside the visible depth range.
		if (!ndcZVisible(v.z)) return;
		const sx = (v.x + 1) * 0.5 * canvasWidth;
		const sy = (1 - v.y) * 0.5 * canvasHeight;
		const screenDist = Math.hypot(sx - px, sy - py);
		const better =
			screenDist < bestScreenDist || (screenDist === bestScreenDist && worldDist < bestWorldDist);
		if (!better) return;
		// Reject dots occluded by a mesh so the nearest visible dot wins — a dot
		// hidden behind a planet must not shadow the one the user can see.
		if (isVisible && !isVisible(v.x, v.y, worldDist)) return;
		bestScreenDist = screenDist;
		bestWorldDist = worldDist;
		bestBody = body;
	};

	for (const body of ctx.bodies.majorBodies) {
		if (body.data.objectType !== ObjectType.MOON) continue;
		if (!ctx.visibility.isMoonGroupVisible(body.data.parentId)) continue;
		testBody(body);
	}

	if (!bestBody) return null;
	return { body: bestBody, distance: bestWorldDist, screenDist: bestScreenDist };
}
