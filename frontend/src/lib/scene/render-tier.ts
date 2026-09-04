import { isCoarsePointer, isLowEndDevice } from '$lib/device';
import { getSettings } from '$lib/state/settings.svelte';

/**
 * GPU class for the fill-bound render knobs. The boot atmosphere calibration
 * is the one measured GPU signal the app has: the shell tier it settles on
 * says how much fill this device affords. Device hints stand in until it runs.
 */
export type RenderTier = 'low' | 'medium' | 'high';

export interface RenderTierPreset {
	/** Device pixel ratio cap for the 3D canvas. Labels are DOM and stay sharp. */
	maxPixelRatio: number;
	/** Shadow map edge for the focused model's contact and self shadows. */
	shadowMapSize: number;
	softShadows: boolean;
	/** Bloom render-target size relative to the canvas. */
	bloomScale: number;
	/** Cloud points drawn at once over every visible group. */
	pointBudget: number;
	/** Highest surface texture tier to decode; the 16k tier is 512 MB of RGBA. */
	maxTextureTier: 'low' | 'medium' | 'high';
	/** Largest skybox face edge, in pixels. */
	maxSkyboxFace: number;
}

export const RENDER_TIER_PRESETS: Record<RenderTier, RenderTierPreset> = {
	low: {
		maxPixelRatio: 1.25,
		shadowMapSize: 1024,
		softShadows: false,
		bloomScale: 0.5,
		pointBudget: 400_000,
		maxTextureTier: 'medium',
		maxSkyboxFace: 2048
	},
	medium: {
		maxPixelRatio: 1.5,
		shadowMapSize: 2048,
		softShadows: true,
		bloomScale: 0.75,
		pointBudget: 900_000,
		maxTextureTier: 'medium',
		maxSkyboxFace: 2048
	},
	high: {
		maxPixelRatio: 2,
		shadowMapSize: 4096,
		softShadows: true,
		bloomScale: 1,
		pointBudget: Infinity,
		maxTextureTier: 'high',
		maxSkyboxFace: Infinity
	}
};

/** Surface texture tier cap: the fill tier and the memory hint both apply. */
export function maxTextureTier(): 'low' | 'medium' | 'high' {
	if (isLowEndDevice()) return 'low';
	return currentRenderTier().maxTextureTier;
}

export function resolveRenderTier(): RenderTier {
	const measured = getSettings().atmosphereCalibration?.tier;
	if (measured === 'low' || measured === 'medium') return measured;
	if (measured === 'high' || measured === 'ultra') return 'high';
	if (isCoarsePointer()) return isLowEndDevice() ? 'low' : 'medium';
	return isLowEndDevice() ? 'medium' : 'high';
}

export function currentRenderTier(): RenderTierPreset {
	return RENDER_TIER_PRESETS[resolveRenderTier()];
}

/** `window.devicePixelRatio` clamped to the tier's cap. The calibration bench
 *  keeps the fixed device cap instead, so its measurement never depends on
 *  its own result. */
export function renderPixelRatio(): number {
	if (typeof window === 'undefined') return 1;
	return Math.min(window.devicePixelRatio, currentRenderTier().maxPixelRatio);
}
