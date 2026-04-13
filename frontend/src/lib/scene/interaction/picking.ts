import type { PerspectiveCamera, Vector2, Vector3 } from 'three';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import type { ContextManager } from '$lib/scene/context-manager.svelte';
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
	const SCREEN_THRESHOLD = pointerType === 'touch' || pointerType === 'pen' ? 16 : 12;
	// Convert NDC pointer to pixel coords
	const px = (pointer.x + 1) * 0.5 * canvasWidth;
	const py = (1 - pointer.y) * 0.5 * canvasHeight;

	const v = tmpV3;
	const [fx, fy, fz] = focusTruePos;
	let bestBody: PositionedBody | undefined;
	let bestScreenDist = SCREEN_THRESHOLD;
	let bestWorldDist = Infinity;

	const testBody = (body: PositionedBody): void => {
		// Point-cloud bodies' positions are advanced on the GPU; refresh the
		// CPU copy from orbital elements at the current jd so picking matches
		// the rendered dot even while paused.
		refreshMinorBodyPosition(body, jd, ctx);
		// Project body position into camera-relative coordinates
		v.set(body.position[0] - fx, body.position[1] - fy, body.position[2] - fz);
		v.project(camera);
		// Behind camera
		if (v.z < 0 || v.z > 1) return;
		const sx = (v.x + 1) * 0.5 * canvasWidth;
		const sy = (1 - v.y) * 0.5 * canvasHeight;
		const screenDist = Math.hypot(sx - px, sy - py);
		if (screenDist < bestScreenDist) {
			bestScreenDist = screenDist;
			bestWorldDist = v.length();
			bestBody = body;
		} else if (screenDist === bestScreenDist && v.length() < bestWorldDist) {
			bestWorldDist = v.length();
			bestBody = body;
		}
	};

	// Visible asteroid zones
	for (const [zone, bodies] of ctx.asteroidBodiesByZone) {
		if (!ctx.isAsteroidGroupVisible(zone)) continue;
		for (const body of bodies) testBody(body);
	}

	// Visible spacecraft groups
	for (const [gid, bodies] of ctx.spacecraftByParent) {
		if (!ctx.isSpacecraftGroupVisible(gid)) continue;
		for (const body of bodies) testBody(body);
	}

	// Visible moon point-cloud groups (moons shown as dots when zoomed out)
	for (const body of ctx.majorBodies) {
		if (body.data.objectType !== ObjectType.MOON) continue;
		if (!ctx.isMoonGroupVisible(body.data.parentId)) continue;
		testBody(body);
	}

	if (!bestBody) return null;
	return { body: bestBody, distance: bestWorldDist };
}
