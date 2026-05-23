import { SphereGeometry, type PerspectiveCamera, type WebGLRenderer } from 'three';
import { ObjectType, effectiveRadiusKm } from '$lib/types/objects';
import { kmToScene } from '$lib/math/units';
import type { ContextManager } from '$lib/scene/context-manager.svelte';
import type { BodyObjects } from '$lib/scene/types';

/** Pixel-radius → segment count, descending. Down-step uses 15% hysteresis. */
const SPHERE_LOD_TIERS = [
	{ up: 150, segs: 128 },
	{ up: 40, segs: 64 },
	{ up: 0, segs: 32 }
];

/** Cap for bodies outside the active system (sun excepted) — they never fill enough screen to matter. */
const OUT_OF_SYSTEM_SPHERE_SEGMENTS = 24;

function desiredSphereSegments(
	screenR: number,
	isStar: boolean,
	inSystem: boolean,
	current: number
): number {
	if (!inSystem && !isStar) return OUT_OF_SYSTEM_SPHERE_SEGMENTS;
	let target = SPHERE_LOD_TIERS[SPHERE_LOD_TIERS.length - 1].segs;
	for (const t of SPHERE_LOD_TIERS) {
		if (screenR >= t.up) {
			target = t.segs;
			break;
		}
	}
	// Hysteresis: only step *down* if we've fallen well below the current
	// tier's up-threshold. Up-steps are immediate.
	if (target < current) {
		const currentTier = SPHERE_LOD_TIERS.find((t) => t.segs === current);
		if (currentTier && screenR >= currentTier.up * 0.85) return current;
	}
	return target;
}

/** Per-frame sphere-geometry LOD: swap `mesh.geometry` when the screen-space pixel radius crosses a tier. */
export function updateSphereLOD(
	bodyObjects: Map<string, BodyObjects>,
	camera: PerspectiveCamera,
	renderer: WebGLRenderer,
	ctx: ContextManager,
	focusedId: string | undefined
): void {
	const fovRad = (camera.fov * Math.PI) / 180;
	const screenH = renderer.domElement.clientHeight;
	const projScale = screenH / (2 * Math.tan(fovRad / 2));
	const activeSystem = ctx.activeSystemId;

	for (const bo of bodyObjects.values()) {
		if (!bo.mesh || !bo.radiusScene || !bo.group.visible) continue;
		if (bo.cachedDist <= 0) continue;
		const screenR = (bo.radiusScene / bo.cachedDist) * projScale;
		const isStar = bo.body.data.objectType === ObjectType.STAR;
		const id = bo.body.data.id;
		const inSystem = activeSystem
			? id === activeSystem || ctx.isInActiveSystem(bo.body.data.parentId)
			: id === focusedId;
		const desired = desiredSphereSegments(screenR, isStar, inSystem, bo.currentSegments ?? 64);
		if (desired === bo.currentSegments) continue;
		const radius = kmToScene(effectiveRadiusKm(bo.body.data));
		const old = bo.mesh.geometry;
		bo.mesh.geometry = new SphereGeometry(radius, desired, desired);
		old.dispose();
		bo.currentSegments = desired;
	}
}
