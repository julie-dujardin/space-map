import type { PerspectiveCamera, TextureLoader, WebGLRenderer } from 'three';
import type { ContextManager } from '$lib/scene/context-manager.svelte';
import type { BodyObjects } from '$lib/scene/types';
import {
	loadBodyTextureTier,
	textureFrameForJd,
	tierRank,
	highestAvailableTier
} from '$lib/scene/objects/construction';
import { cloudFrameForJd, loadCloudTexture } from '$lib/scene/objects/clouds';

/**
 * Per-frame texture LOD: upgrade each visible body's texture tier based on
 * its screen-space radius. One-way upgrade — the prior texture is disposed
 * when a higher tier loads, so at most one tier per body lives on the GPU.
 */
export function updateTextureLOD(
	bodyObjects: Map<string, BodyObjects>,
	camera: PerspectiveCamera,
	renderer: WebGLRenderer,
	ctx: ContextManager,
	textureLoader: TextureLoader,
	focusedId: string | undefined,
	jd: number
): void {
	const fovRad = (camera.fov * Math.PI) / 180;
	const screenH = renderer.domElement.clientHeight;
	const projScale = screenH / (2 * Math.tan(fovRad / 2));
	const activeSystem = ctx.activeSystemId;

	for (const bo of bodyObjects.values()) {
		if (!bo.mesh || !bo.radiusScene || !bo.group.visible) continue;
		if (!bo.availableTiers?.length) continue;
		if (bo.cachedDist <= 0) continue;
		const id = bo.body.data.id;
		if (activeSystem) {
			if (id !== activeSystem && !ctx.isInActiveSystem(bo.body.data.parentId)) continue;
		} else if (id !== focusedId) {
			continue;
		}

		const screenR = (bo.radiusScene / bo.cachedDist) * projScale;
		const altitudeRadii = bo.cachedDist / bo.radiusScene;
		let desired: 'low' | 'medium' | 'high';
		if (screenR < 256 && altitudeRadii > 10) desired = 'low';
		else if (screenR < 1024 && altitudeRadii > 2) desired = 'medium';
		else desired = 'high';

		const currentRank = tierRank(bo.textureTier);
		const desiredRank = tierRank(desired);
		const desiredFrame = textureFrameForJd(jd, bo.availableFrames);
		const frameChanged = desiredFrame !== bo.textureFrame;
		const wantsUpgrade = desiredRank > currentRank;

		// The cloud nudge below sits outside this gate so direct-load at
		// high zoom doesn't strand clouds at low while their initial fetch
		// is still resolving.
		if (!bo.textureLoading && (wantsUpgrade || frameChanged)) {
			const target = wantsUpgrade
				? highestAvailableTier(desiredRank, bo.availableTiers)
				: bo.textureTier;
			if (target) loadBodyTextureTier(bo, target, desiredFrame, textureLoader);
		}

		// Clamp to whatever the cloud bundle actually exports — it may
		// top out below the surface's tier (silent no-op otherwise). The
		// frame slides separately with sim time, picking the closest
		// snapshot from the exported set.
		if (bo.clouds && bo.textureTier) {
			const cloudTarget = highestAvailableTier(tierRank(bo.textureTier), bo.clouds.availableTiers);
			const cloudFrame = cloudFrameForJd(jd, bo.clouds.availableFrames);
			if (cloudTarget && cloudFrame) {
				loadCloudTexture(bo.clouds, cloudTarget, cloudFrame);
			}
		}
	}
}
