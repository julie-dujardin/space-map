import type { WebGLRenderer } from 'three';
import type { PositionedBody } from '$lib/types/objects';
import type { BodyObjects } from '$lib/scene/types';
import type { OrbitWorkerPool } from '$lib/math/orbit/pool';
import { AU_SCALE } from '$lib/math/units';

export interface DebugStats {
	fps: number;
	workers: number;
	workerGroups: number;
	drawCalls: number;
	triangles: number;
	geometries: number;
	textures: number;
	programs: number;
	promotedBodies: number;
	focusedId: string | undefined;
	focusedName: string | undefined;
	cameraDistanceAU: number;
	viewportW: number;
	viewportH: number;
	pixelRatio: number;
}

/** Snapshot of renderer internals for the debug overlay. Read on demand. */
export function collectDebugStats(params: {
	fps: number;
	orbitPool: OrbitWorkerPool;
	renderer: WebGLRenderer;
	bodyObjects: Map<string, BodyObjects>;
	focusedBody: PositionedBody | undefined;
	cameraDistanceScene: number;
}): DebugStats {
	const { fps, orbitPool, renderer, bodyObjects, focusedBody, cameraDistanceScene } = params;
	const info = renderer.info;
	return {
		fps,
		workers: orbitPool.workerCount,
		workerGroups: orbitPool.groupCount,
		drawCalls: info.render.calls,
		triangles: info.render.triangles,
		geometries: info.memory.geometries,
		textures: info.memory.textures,
		programs: info.programs?.length ?? 0,
		promotedBodies: bodyObjects.size,
		focusedId: focusedBody?.data.id,
		focusedName: focusedBody?.data.name ?? undefined,
		cameraDistanceAU: cameraDistanceScene / AU_SCALE,
		viewportW: renderer.domElement.clientWidth,
		viewportH: renderer.domElement.clientHeight,
		pixelRatio: renderer.getPixelRatio()
	};
}
