/**
 * Coarse device-capability probes used to shed memory/bandwidth on low-end and
 * data-saver clients. All signals are Chromium-only (`deviceMemory`, `saveData`
 * are unsupported in Safari/Firefox, where these read as "not constrained") —
 * so this only ever *relaxes* work, never blocks a capable device.
 */

interface DeviceMemoryNavigator {
	deviceMemory?: number;
	connection?: { saveData?: boolean };
}

/** RAM at or below this (GiB) counts as low-end. `deviceMemory` is quantised
 *  and privacy-capped at 8, so 4 is the typical phone reading. */
const LOW_MEMORY_GIB = 4;

/** Max device pixel ratio we ever render at. Bloom + the composer's offscreen
 *  targets cost quadratically in DPR, so uncapped DPR-3 phones pay ~2.25× the
 *  fill of this cap for no visible gain. Mirrors `BodyLineup`. */
export const MAX_PIXEL_RATIO = 2;

/** Data-saver requested via `Save-Data`. Explicit user intent to minimise
 *  transfer — honoured independently of memory. */
export function prefersReducedData(): boolean {
	if (typeof navigator === 'undefined') return false;
	return (navigator as DeviceMemoryNavigator).connection?.saveData === true;
}

/**
 * True when the client is memory-constrained or has asked to save data, in
 * which case callers skip the heaviest optional assets (the deferred belt wave,
 * per-body DEM relief, rough shape meshes). Conservative: an unknown device is
 * treated as capable.
 */
export function isLowEndDevice(): boolean {
	if (typeof navigator === 'undefined') return false;
	if (prefersReducedData()) return true;
	const mem = (navigator as DeviceMemoryNavigator).deviceMemory;
	return typeof mem === 'number' && mem > 0 && mem <= LOW_MEMORY_GIB;
}

/** Primary pointer is coarse (touch) — the phone/tablet signal. Memoised:
 *  docking a keyboard mid-session shouldn't flip render quality under the user. */
let coarsePointer: boolean | undefined;
export function isCoarsePointer(): boolean {
	if (coarsePointer === undefined) {
		coarsePointer =
			typeof window !== 'undefined' && !!window.matchMedia?.('(pointer: coarse)').matches;
	}
	return coarsePointer;
}

/** `window.devicePixelRatio` clamped to {@link MAX_PIXEL_RATIO}. */
export function cappedPixelRatio(): number {
	if (typeof window === 'undefined') return 1;
	return Math.min(window.devicePixelRatio, MAX_PIXEL_RATIO);
}
