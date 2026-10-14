import { isCoarsePointer, isLowEndDevice } from '$lib/device';
import { sceneSettings } from '$lib/scene/settings.svelte';

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
	/** Samples for each pixel of the scene's render target, to smooth the
	 *  edges. None: an edge has steps of one pixel. Four cost 2 to 3 ms a frame
	 *  on a GPU of the low tier. */
	sceneSamples: number;
	/** Cloud points drawn at once over every visible group. */
	pointBudget: number;
	/** Highest surface texture tier to decode; the 16k tier is 512 MB of RGBA. */
	maxTextureTier: 'low' | 'medium' | 'high';
	/** Surface tile windows drawn for one body, 64 MB of RGBA each. One more
	 *  is held to load a window on before it replaces another. */
	tileWindows: number;
	/** Height tile windows drawn for one body, and one more held: 32 MB each,
	 *  64 MB near a patch. */
	reliefWindows: number;
	/** Samples of the ray that finds the ground's own shadow in the height
	 *  tiles, for each pixel of lit ground. None: the whole-globe map casts
	 *  the shadows there too. */
	reliefShadowSteps: number;
	/** Cells from one band of the terrain grid to the next. At ground level the
	 *  grid has about (125 + 14 × this)² vertices. */
	terrainBandCells: number;
	/** Largest skybox face edge, in pixels. */
	maxSkyboxFace: number;
}

export const RENDER_TIER_PRESETS: Record<RenderTier, RenderTierPreset> = {
	low: {
		maxPixelRatio: 1.25,
		shadowMapSize: 1024,
		softShadows: false,
		bloomScale: 0.5,
		sceneSamples: 0,
		pointBudget: 400_000,
		maxTextureTier: 'medium',
		tileWindows: 3,
		reliefWindows: 2,
		reliefShadowSteps: 12,
		terrainBandCells: 16,
		maxSkyboxFace: 2048
	},
	medium: {
		maxPixelRatio: 1.5,
		shadowMapSize: 2048,
		softShadows: true,
		bloomScale: 0.75,
		sceneSamples: 4,
		pointBudget: 900_000,
		maxTextureTier: 'medium',
		tileWindows: 4,
		reliefWindows: 3,
		reliefShadowSteps: 16,
		terrainBandCells: 24,
		maxSkyboxFace: 2048
	},
	high: {
		maxPixelRatio: 2,
		shadowMapSize: 4096,
		softShadows: true,
		bloomScale: 1,
		sceneSamples: 4,
		pointBudget: Infinity,
		maxTextureTier: 'high',
		tileWindows: 6,
		reliefWindows: 4,
		reliefShadowSteps: 32,
		terrainBandCells: 32,
		maxSkyboxFace: Infinity
	}
};

/** Surface texture tier cap: the fill tier and the memory hint both apply. */
export function maxTextureTier(): 'low' | 'medium' | 'high' {
	if (isLowEndDevice()) return 'low';
	return currentRenderTier().maxTextureTier;
}

/** Surface tile windows a body may hold; none where memory is short. */
export function maxTileWindows(): number {
	if (isLowEndDevice()) return 0;
	return currentRenderTier().tileWindows;
}

/** Height tile windows a body may hold; none where memory is short. */
export function maxReliefWindows(): number {
	if (isLowEndDevice()) return 0;
	return currentRenderTier().reliefWindows;
}

/** Samples of a shadow ray through the height tiles; see the preset. */
export function reliefShadowSteps(): number {
	return currentRenderTier().reliefShadowSteps;
}

export function resolveRenderTier(): RenderTier {
	const measured = sceneSettings().atmosphereCalibration?.tier;
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
