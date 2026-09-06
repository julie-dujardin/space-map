import type {
	AtmosphereCalibration,
	AtmosphereQualityConfig,
	AtmosphereQualityTier,
	ResolvedAtmosphereTier
} from './objects/surface/atmosphere-quality';

/**
 * The display settings the scene reads. The app's persisted store satisfies
 * this structurally; an embed passes its own or takes the default. One per
 * page, registered through {@link setSceneSettings}: the tier and quality
 * helpers run deep in material code with no map instance at hand.
 */
export interface SceneSettings {
	resolvedReducedMotion: boolean;
	viewMode: 'map' | 'immersive';
	showClouds: boolean;
	showAtmospheres: boolean;
	atmosphereQuality: AtmosphereQualityTier;
	atmosphereAutoTier: ResolvedAtmosphereTier | null;
	atmosphereCalibration: AtmosphereCalibration | null;
	atmoQualityOverrides: Partial<AtmosphereQualityConfig>;
	highAmbient: boolean;
	realisticLighting: boolean;
	overexposeRings: boolean;
	showShapeMesh: boolean;
	showSurfaceTexture: boolean;
	showDisplacement: boolean;
	showSelfShadow: boolean;
	showHaloDebug: boolean;
	maxPartsPerZone: number;
	/** Written by the boot calibration and the perf governor. */
	setAtmosphereCalibration(v: AtmosphereCalibration | null): void;
	setAtmosphereAutoTier(v: ResolvedAtmosphereTier | null): void;
}

/** What a bare embed renders with: everything on, quality measured at boot.
 *  Reactive, so the calibration's tier reaches the renderer through the same
 *  effects a host's own store drives. */
export function defaultSceneSettings(): SceneSettings {
	const settings = $state<SceneSettings>({
		resolvedReducedMotion:
			typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches,
		viewMode: 'map',
		showClouds: true,
		showAtmospheres: true,
		atmosphereQuality: 'auto',
		atmosphereAutoTier: null,
		atmosphereCalibration: null,
		atmoQualityOverrides: {},
		highAmbient: false,
		realisticLighting: false,
		overexposeRings: false,
		showShapeMesh: true,
		showSurfaceTexture: true,
		showDisplacement: true,
		showSelfShadow: true,
		showHaloDebug: false,
		maxPartsPerZone: 0,
		setAtmosphereCalibration(v) {
			this.atmosphereCalibration = v;
		},
		setAtmosphereAutoTier(v) {
			this.atmosphereAutoTier = v;
		}
	});
	return settings;
}

let current: SceneSettings | null = null;

export function sceneSettings(): SceneSettings {
	return (current ??= defaultSceneSettings());
}

export function setSceneSettings(settings: SceneSettings): void {
	current = settings;
}
