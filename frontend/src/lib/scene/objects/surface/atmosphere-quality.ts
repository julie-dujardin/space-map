import { isCoarsePointer, isLowEndDevice } from '$lib/device';
import { getSettings } from '$lib/state/settings.svelte';

/**
 * Quality knobs for the atmosphere shells. The ray march costs
 * primarySteps × (lightSteps + per-sample shadow work) per fragment over the
 * planet's whole screen footprint, which desktop GPUs shrug off and phones
 * don't — tiers keep one shader with compile-time defines instead of forking
 * cheap/fancy implementations.
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
	/** Render the sky from inside a shell (BackSide flip + the full-scene
	 *  opaque-depth prepass + skybox dimming). Off = the shell simply vanishes
	 *  once entered, and the prepass is never paid. */
	insideView: boolean;
}

export type ResolvedAtmosphereTier = 'low' | 'medium' | 'high' | 'ultra';
export type AtmosphereQualityTier = 'auto' | ResolvedAtmosphereTier;

/** Step-down ladder for the perf governor, worst → best. */
const TIER_ORDER: ResolvedAtmosphereTier[] = ['low', 'medium', 'high', 'ultra'];

export const ATMOSPHERE_QUALITY_PRESETS: Record<ResolvedAtmosphereTier, AtmosphereQualityConfig> = {
	low: {
		primarySteps: 12,
		lightSteps: 3,
		eclipseShadows: false,
		ringShadows: false,
		insideView: false
	},
	// Low's march budget with the full feature set — the phone tier.
	medium: {
		primarySteps: 12,
		lightSteps: 3,
		eclipseShadows: true,
		ringShadows: true,
		insideView: true
	},
	high: {
		primarySteps: 16,
		lightSteps: 4,
		eclipseShadows: true,
		ringShadows: true,
		insideView: true
	},
	ultra: {
		primarySteps: 32,
		lightSteps: 8,
		eclipseShadows: true,
		ringShadows: true,
		insideView: true
	}
};

/**
 * Resolve 'auto': a tier the perf governor has settled on wins; otherwise a
 * first guess from coarse device signals — phones/tablets start at medium,
 * desktops at ultra, and the Chromium-only low-end probe steps either down one.
 * Optimistic starts are fine because {@link recordAtmospherePerf} walks the
 * tier down as soon as sustained frame times prove the guess wrong.
 */
export function resolveAtmosphereTier(tier: AtmosphereQualityTier): ResolvedAtmosphereTier {
	if (tier !== 'auto') return tier;
	const learned = getSettings().atmosphereAutoTier;
	if (learned) return learned;
	if (isCoarsePointer()) return isLowEndDevice() ? 'low' : 'medium';
	return isLowEndDevice() ? 'high' : 'ultra';
}

/** The effective config right now: resolved tier preset + session debug overrides. */
export function currentAtmosphereConfig(): AtmosphereQualityConfig {
	const s = getSettings();
	return {
		...ATMOSPHERE_QUALITY_PRESETS[resolveAtmosphereTier(s.atmosphereQuality)],
		...s.atmoQualityOverrides
	};
}

/** Identity key for change detection — shells rebuild their program when the
 *  key they were compiled with stops matching. */
export function atmosphereConfigKey(c: AtmosphereQualityConfig): string {
	return `${c.primarySteps}|${c.lightSteps}|${+c.eclipseShadows}|${+c.ringShadows}|${+c.insideView}`;
}

// Perf governor state. FPS is an EMA (~0.5 s time constant) so one dropped
// frame can't trip it; the low-FPS clock only runs while a shell actually
// covers a meaningful part of the view, so unrelated jank (chunk loads, big
// point clouds) doesn't get blamed on the atmosphere.
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
 * sustained sub-{@link LOW_FPS} frames with a shell prominent steps the learned
 * tier down one and persists it ({@link resolveAtmosphereTier} then starts
 * there on every future load). Down only — recovering from an unlucky
 * downgrade is a manual tier pick. Any config change (tier step, debug
 * override) re-arms a grace period so compile hitches don't count.
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
