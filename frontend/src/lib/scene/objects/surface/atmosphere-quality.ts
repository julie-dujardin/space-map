import { isCoarsePointer, isLowEndDevice } from '$lib/device';
import { getSettings } from '$lib/state/settings.svelte';

/**
 * Quality knobs for the atmosphere shells. Ray march cost is
 * primarySteps × (lightSteps + shadow work) per fragment, over the planet's
 * whole footprint — tiers pick compile-time defines instead of forking shaders.
 */
export interface AtmosphereQualityConfig {
	/** View-ray march samples. */
	primarySteps: number;
	/** Sun-ray samples per view sample. */
	lightSteps: number;
	/** March eclipse occluders (moon shadows sweeping the air column). */
	eclipseShadows: boolean;
	/** March the ring-shadow profile through the air column. */
	ringShadows: boolean;
	/** Sky rendered from inside a shell (BackSide flip + opaque-depth prepass + skybox dimming). Off = shell vanishes once entered. */
	insideView: boolean;
	/** Sun-transmittance tints (sunset light, disc chroma, corona). Off on low tiers: surface march covers full-screen landed terrain. */
	sunTint: boolean;
	/** Piecewise Mie density profiles (Venus decks, Titan haze): two LUT taps per sample instead of one exp — high/ultra. */
	layeredDensity: boolean;
	/** Ground-bounce boost on multiple-scatter ambient. Reuses already-marched densities — free, on everywhere. */
	groundAlbedo: boolean;
	/** Mars seasonal dust/pressure cycle. CPU-only, on everywhere. */
	seasonal: boolean;
	/** Refraction lift of the Sun seen from inside a shell. CPU-only, on everywhere. */
	refraction: boolean;
}

export type ResolvedAtmosphereTier = 'low' | 'medium' | 'high' | 'ultra';
export type AtmosphereQualityTier = 'auto' | ResolvedAtmosphereTier;

/** Step-down ladder for the perf governor, worst → best. */
const TIER_ORDER: ResolvedAtmosphereTier[] = ['low', 'medium', 'high', 'ultra'];

// March budget is the main degrade lever; sunTint is the exception, since
// its surface march targets exactly the devices the low tiers are for.
export const ATMOSPHERE_QUALITY_PRESETS: Record<ResolvedAtmosphereTier, AtmosphereQualityConfig> = {
	low: {
		primarySteps: 6,
		lightSteps: 2,
		eclipseShadows: true,
		ringShadows: true,
		insideView: true,
		sunTint: false,
		layeredDensity: false,
		groundAlbedo: true,
		seasonal: true,
		refraction: true
	},
	medium: {
		primarySteps: 12,
		lightSteps: 3,
		eclipseShadows: true,
		ringShadows: true,
		insideView: true,
		sunTint: false,
		layeredDensity: false,
		groundAlbedo: true,
		seasonal: true,
		refraction: true
	},
	high: {
		primarySteps: 16,
		lightSteps: 4,
		eclipseShadows: true,
		ringShadows: true,
		insideView: true,
		sunTint: true,
		layeredDensity: true,
		groundAlbedo: true,
		seasonal: true,
		refraction: true
	},
	ultra: {
		primarySteps: 32,
		lightSteps: 8,
		eclipseShadows: true,
		ringShadows: true,
		insideView: true,
		sunTint: true,
		layeredDensity: true,
		groundAlbedo: true,
		seasonal: true,
		refraction: true
	}
};

/** Boot-time benchmark result (see perf/atmosphere-calibration.ts). */
export interface AtmosphereCalibration {
	/** GPU + resolution identity the run is valid for — a mismatch re-calibrates. */
	key: string;
	tier: ResolvedAtmosphereTier;
	/** Worse-scenario median per measured tier, so thresholds can be re-derived
	 *  without another run. */
	worstMs: Partial<Record<ResolvedAtmosphereTier, number>>;
}

/** First guess from device signals: phones/tablets start medium, desktops ultra, the low-end probe steps either down one. */
export function heuristicAtmosphereTier(): ResolvedAtmosphereTier {
	if (isCoarsePointer()) return isLowEndDevice() ? 'low' : 'medium';
	return isLowEndDevice() ? 'high' : 'ultra';
}

/** Resolve 'auto': perf-governor tier wins (cleared each fresh calibration), else boot-benchmark tier, else the device-signal guess. */
export function resolveAtmosphereTier(tier: AtmosphereQualityTier): ResolvedAtmosphereTier {
	if (tier !== 'auto') return tier;
	const s = getSettings();
	return s.atmosphereAutoTier ?? s.atmosphereCalibration?.tier ?? heuristicAtmosphereTier();
}

/** The effective config right now: resolved tier preset + session debug overrides. */
export function currentAtmosphereConfig(): AtmosphereQualityConfig {
	const s = getSettings();
	return {
		...ATMOSPHERE_QUALITY_PRESETS[resolveAtmosphereTier(s.atmosphereQuality)],
		...s.atmoQualityOverrides
	};
}

/** Identity key: shells rebuild their program when it stops matching. Uniform/CPU-gated fields (sunTint, groundAlbedo, seasonal, refraction) stay out. */
export function atmosphereConfigKey(c: AtmosphereQualityConfig): string {
	return `${c.primarySteps}|${c.lightSteps}|${+c.eclipseShadows}|${+c.ringShadows}|${+c.insideView}|${+c.layeredDensity}`;
}

// Perf governor state. FPS is an EMA (~0.5s) so one dropped frame can't trip
// it; the low-FPS clock only runs while a shell is prominent, so unrelated
// jank isn't blamed on the atmosphere.
const LOW_FPS = 30;
const OK_FPS = 45;
const SUSTAIN_MS = 3000;
const GRACE_MS = 2500;
const HITCH_MS = 250;

let fpsEma = 60;
let lowMs = 0;
let graceMs = GRACE_MS;
let lastConfigKey = '';

/**
 * Feed one frame to the perf governor. In auto mode, ≥{@link SUSTAIN_MS} of
 * sustained sub-{@link LOW_FPS} frames with a shell prominent steps the tier
 * down one and persists it. Down only — recovering is a manual tier pick.
 * Any config change re-arms a grace period so compile hitches don't count.
 */
export function recordAtmospherePerf(dtMs: number, shellProminent: boolean): void {
	const s = getSettings();
	if (s.atmosphereQuality !== 'auto' || dtMs <= 0 || dtMs > HITCH_MS) return;
	const key = atmosphereConfigKey(currentAtmosphereConfig());
	if (key !== lastConfigKey) {
		lastConfigKey = key;
		graceMs = GRACE_MS;
		lowMs = 0;
		fpsEma = 60;
	}
	fpsEma += (1000 / dtMs - fpsEma) * Math.min(1, dtMs / 500);
	if (graceMs > 0) {
		graceMs -= dtMs;
		return;
	}
	if (!shellProminent || fpsEma > OK_FPS) {
		lowMs = Math.max(0, lowMs - dtMs);
		return;
	}
	if (fpsEma >= LOW_FPS) return; // between the thresholds: hold, don't decide
	lowMs += dtMs;
	if (lowMs < SUSTAIN_MS) return;
	lowMs = 0;
	const below = TIER_ORDER[TIER_ORDER.indexOf(resolveAtmosphereTier('auto')) - 1];
	if (below) s.setAtmosphereAutoTier(below);
}
