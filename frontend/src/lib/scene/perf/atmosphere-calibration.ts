import { WebGLRenderer } from 'three';
import { cappedPixelRatio } from '$lib/device';
import { getSettings } from '$lib/state/settings.svelte';
import {
	heuristicAtmosphereTier,
	type ResolvedAtmosphereTier
} from '$lib/scene/objects/surface/atmosphere-quality';
import {
	gpuLabel,
	pickTier,
	runAdaptiveAtmosphereBenchmark,
	tierWorstMs
} from './atmosphere-benchmark';
import { calibrationUi } from './calibration-state.svelte';

/**
 * Boot-time calibration: runs the atmosphere benchmark against a hidden
 * canvas once per device (result persisted in settings, keyed by GPU +
 * resolution) so 'auto' quality starts from a measured tier instead of coarse
 * device signals. It runs behind the initial loading screen, concurrent with
 * the network loads but never with the live scene.
 */

/** A tier must hold this shell-only rate in its worse scenario. */
const TARGET_FPS = 60;

/** Just enough for the loading screen to paint before the bench claims the GPU. */
const START_DELAY_MS = 100;

/** Backstop on holding the loading screen: a stalled bench (rAF throttled in a
 *  background tab, driver weirdness) releases the app and keeps running —
 *  contended like the old behavior, but only in that degraded case, and the
 *  result still stores for next load. */
const BOOT_HOLD_MAX_MS = 30_000;

/** Resolution enters the key as a coarse pixel-count bucket: cost scales with
 *  pixels, but desktop window sizes vary a little every boot and phones rotate
 *  — neither should invalidate a run. */
const PIXEL_BUCKET = 250_000;

/** Bump to invalidate stored calibrations when the methodology changes. */
const KEY_VERSION = 'v1';

let started = false;
let inFlight: Promise<void> | null = null;

function calibrationKey(renderer: WebGLRenderer): string {
	const gl = renderer.getContext();
	const bucket = Math.round((gl.drawingBufferWidth * gl.drawingBufferHeight) / PIXEL_BUCKET);
	return `${gpuLabel(renderer)}|${bucket}|${KEY_VERSION}`;
}

/** Fire-and-forget from the map page, in parallel with the initial data loads.
 *  The loading screen holds until this settles ({@link calibrationUi.bootPending}),
 *  so the bench never competes with the live scene. At most one run per
 *  session, and none when a stored calibration still matches this device. */
export function scheduleAtmosphereCalibration(): void {
	if (started || typeof window === 'undefined') return;
	started = true;
	calibrationUi.bootPending = true;
	setTimeout(() => (calibrationUi.bootPending = false), BOOT_HOLD_MAX_MS);
	setTimeout(() => {
		void runCalibration(false).finally(() => (calibrationUi.bootPending = false));
	}, START_DELAY_MS);
}

/** Settings-menu re-run: measures again even when a stored result matches.
 *  Resolves when the run (or the one already in flight) finishes. */
export function recalibrateAtmosphere(): Promise<void> {
	return runCalibration(true);
}

function runCalibration(force: boolean): Promise<void> {
	inFlight ??= calibrate(force).finally(() => (inFlight = null));
	return inFlight;
}

async function calibrate(force: boolean): Promise<void> {
	const s = getSettings();
	// Explicit tier or atmospheres off: the user opted out of auto costs.
	if (!force && (s.atmosphereQuality !== 'auto' || !s.showAtmospheres)) return;
	let renderer: WebGLRenderer | null = null;
	try {
		renderer = new WebGLRenderer({ canvas: document.createElement('canvas'), antialias: true });
		renderer.setPixelRatio(cappedPixelRatio());
		renderer.setSize(window.innerWidth, window.innerHeight, false);
		const key = calibrationKey(renderer);
		if (!force && s.atmosphereCalibration?.key === key) return;

		// Both consumers read calibrationUi.progress: the boot loading screen,
		// and the settings re-run overlay (which also pauses the map via Scene's
		// effect — at boot the map isn't mounted, so that's a no-op).
		calibrationUi.progress = 0;
		// Adaptive: walks the tier ladder from the device-signal guess to the
		// budget boundary, so only the tiers that decide the pick get measured.
		const report = await runAdaptiveAtmosphereBenchmark(renderer, {
			budgetMs: 1000 / TARGET_FPS,
			startTier: heuristicAtmosphereTier(),
			onProgress: (p) => (calibrationUi.progress = p.fraction)
		});
		const worstMs: Partial<Record<ResolvedAtmosphereTier, number>> = {};
		for (const t of report.tiers) {
			const worst = tierWorstMs(t);
			if (!Number.isNaN(worst)) worstMs[t.tier] = Math.round(worst * 100) / 100;
		}
		const tier = pickTier(report, 1000 / TARGET_FPS);
		s.setAtmosphereCalibration({ key, tier, worstMs });
		// A learned governor downgrade predates this measurement — let it re-learn
		// from the calibrated start.
		s.setAtmosphereAutoTier(null);
		console.info(`atmosphere calibration: ${tier}`, worstMs);
	} catch (e) {
		console.warn('atmosphere calibration failed, keeping heuristic tier', e);
	} finally {
		calibrationUi.progress = null;
		renderer?.dispose();
		renderer?.forceContextLoss();
	}
}
