import type { PerspectiveCamera, Vector2, Vector3 } from 'three';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { refreshMinorBodyPosition } from '$lib/scene/minor-body-position';
import type { Vec3 } from '../animation/math';

/** Find the closest visible point-cloud body to the given pointer (NDC). */
export function pickPointCloudBody(
	pointer: Vector2,
	camera: PerspectiveCamera,
	ctx: ContextManager,
	focusTruePos: Vec3,
	canvasWidth: number,
	canvasHeight: number,
	tmpV3: Vector3,
	jd: number,
	pointerType: string
): { body: PositionedBody; distance: number } | null {
	// TODO: earth still focus-steals a lot. Maybe de-prioritise very large objects?
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
		// Point-cloud bodies' positions are advanced on the GPU; refresh the
		// CPU copy from orbital elements at the current jd so picking matches
		// the rendered dot even while paused.
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
		// pushing NDC z outside [-1, 1].
		if (v.z < -1 || v.z > 1) return;
		const sx = (v.x + 1) * 0.5 * canvasWidth;
		const sy = (1 - v.y) * 0.5 * canvasHeight;
		const screenDist = Math.hypot(sx - px, sy - py);
		if (screenDist < bestScreenDist) {
			bestScreenDist = screenDist;
			bestWorldDist = worldDist;
			bestBody = body;
		} else if (screenDist === bestScreenDist && worldDist < bestWorldDist) {
			bestWorldDist = worldDist;
			bestBody = body;
		}
	};

	// A definitive hit (cursor effectively on a dot) lets us bail before
	// scanning the long tail — MBA alone holds ~1.3M asteroids.
	const DEFINITIVE_PX = pointerType === 'touch' || pointerType === 'pen' ? 16 : 8;

	// Moons are few; test them all up front so they outrank overlapping
	// asteroid dots in dense regions.
	for (const body of ctx.bodies.majorBodies) {
		if (body.data.objectType !== ObjectType.MOON) continue;
		if (!ctx.visibility.isMoonGroupVisible(body.data.parentId)) continue;
		testBody(body);
	}

	// Round-robin asteroid zones + spacecraft groups one loader-chunk
	// (10k bodies) at a time, so every visible bucket gets sampled before
	// we commit to a deep scan of any one zone. Bail at the end of each
	// bucket's slice once we have a definitive hit.
	if (bestScreenDist > DEFINITIVE_PX) {
		const CHUNK_BAIL_SIZE = 10_000;
		const iters: IterableIterator<PositionedBody>[] = [];
		for (const [zone, byId] of ctx.bodies.asteroidBodiesByZone) {
			if (ctx.visibility.isAsteroidGroupVisible(zone)) iters.push(byId.values());
		}
		for (const [gid, byId] of ctx.bodies.spacecraftByParent) {
			if (ctx.visibility.isSpacecraftGroupVisible(gid)) iters.push(byId.values());
		}

		let anyProgress = true;
		outer: while (anyProgress) {
			anyProgress = false;
			for (const it of iters) {
				for (let i = 0; i < CHUNK_BAIL_SIZE; i++) {
					const next = it.next();
					if (next.done) break;
					testBody(next.value);
					anyProgress = true;
				}
				if (bestScreenDist <= DEFINITIVE_PX) break outer;
			}
		}
	}

	if (!bestBody) return null;
	return { body: bestBody, distance: bestWorldDist };
}
