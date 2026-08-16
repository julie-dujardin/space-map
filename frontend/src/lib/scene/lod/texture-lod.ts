import type { PerspectiveCamera, TextureLoader, WebGLRenderer } from 'three';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { BodyObjects } from '$lib/scene/types';
import {
	loadBodyTextureTier,
	textureFrameForJd,
	tierRank,
	highestAvailableTier
} from '$lib/scene/objects/body/textures';
import { cloudFrameForJd, loadCloudTexture } from '$lib/scene/objects/surface/clouds';
import { swapDisplacementTier } from '$lib/scene/objects/surface/displacement';
import { getSettings } from '$lib/state/settings.svelte';

/** DEM tier by altitude (in body radii from the center, like `altitudeRadii`),
 *  with wide hysteresis — a swap is a multi-MB fetch + full CPU decode. */
function desiredDemTier(altitudeRadii: number, current: string): string {
	const up = altitudeRadii < 1.05 ? 'high' : altitudeRadii < 4 ? 'medium' : 'low';
	if (tierRank(up) > tierRank(current)) return up;
	const down = altitudeRadii > 7 ? 'low' : altitudeRadii > 1.15 ? 'medium' : 'high';
	if (tierRank(down) < tierRank(current)) return down;
	return current;
}

/** Per-frame texture LOD: upgrade tier by screen-space radius. One-way — prior tier disposed. */
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
	const activeSystem = ctx.visibility.activeSystemId;
	const settings = getSettings();
	const showClouds = settings.showClouds;

	// Sync cloud-mesh visibility unconditionally — the LOD gate below skips
	// bodies outside the active system, but visibility needs to track every
	// body that has a cloud node so the user toggle covers them all.
	for (const bo of bodyObjects.values()) {
		if (bo.clouds) bo.clouds.mesh.visible = showClouds;
	}

	for (const bo of bodyObjects.values()) {
		if (!bo.mesh || !bo.radiusScene || !bo.group.visible) continue;
		if (!bo.availableTiers?.length) continue;
		if (bo.cachedDist <= 0) continue;
		const id = bo.body.data.id;
		if (activeSystem) {
			if (id !== activeSystem && !ctx.visibility.isInActiveSystem(bo.body.data.parentId)) continue;
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

		// Cloud nudge sits outside this gate so a direct high-zoom load doesn't
		// strand clouds at low while the surface fetch is in flight.
		// Debug: with surface texture off, don't let LOD re-load what unload cleared.
		if (settings.showSurfaceTexture && !bo.textureLoading && (wantsUpgrade || frameChanged)) {
			const target = wantsUpgrade
				? highestAvailableTier(desiredRank, bo.availableTiers)
				: bo.textureTier;
			if (target) loadBodyTextureTier(bo, target, desiredFrame, textureLoader);
		}

		// Tier rank capped by maxTextureSize: DataTextures aren't resized by three,
		// so a 16k upload on an 8k-limit GPU would error out.
		const dispTiers = bo.displacementMeta?.tiers;
		if (bo.displacementMap && dispTiers?.length && !bo.displacementLoading) {
			const maxTex = renderer.capabilities.maxTextureSize;
			const capRank = maxTex >= 16383 ? 2 : maxTex >= 8192 ? 1 : 0;
			const current = bo.displacementTier ?? 'low';
			const target = highestAvailableTier(
				Math.min(tierRank(desiredDemTier(altitudeRadii, current)), capRank),
				dispTiers
			);
			if (target && target !== current) void swapDisplacementTier(bo, target);
		}

		// Clamp to whatever the cloud bundle exports (may top out below the
		// surface tier); frame slides separately with sim time.
		if (bo.clouds && bo.textureTier) {
			const cloudTarget = highestAvailableTier(tierRank(bo.textureTier), bo.clouds.availableTiers);
			const cloudFrame = cloudFrameForJd(jd, bo.clouds.availableFrames);
			if (cloudTarget && cloudFrame) {
				loadCloudTexture(bo.clouds, cloudTarget, cloudFrame);
			}
		}
	}
}
