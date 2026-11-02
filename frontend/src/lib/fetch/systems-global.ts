/**
 * Always-loaded systems metadata from `/data/v1/systems/global.json`. The
 * per-system `systems/naif-{N}.json` files load later. It holds the GM per NAIF
 * id (km³/s², with the Sun's GM for the SSB) for trail-buffer period estimates,
 * and the IAU nutation/precession angles per planetary-system owner. The angles
 * pair with each body's `nut_prec` to give its pole and spin.
 */

import { naifId } from '$lib/constants';
import type { NutPrec, NutPrecSums } from '$lib/math/orientation';
import { dataBase } from './data-base';
import { fetchWithTimeout } from './fetch-timeout';
import { untilOnline } from './online';
import { RetryBackoff } from './retry-backoff';

type NutPrecPhases = Pick<NutPrec, 'angles' | 'phaseDegree'>;

const phases = new Map<number, NutPrecPhases>();
const gmKm3s2 = new Map<number, number>();
let loadPromise: Promise<void> | null = null;
let loaded = false;
/** The data host answered that it has no global.json: asking again will not
 *  change that. */
let absent = false;
const listeners = new Set<() => void>();

const RETRY_KEY = 'global';
const retry = new RetryBackoff<typeof RETRY_KEY>(() => void askAgain());

/** A load answered with an error status. */
class StatusError extends Error {
	constructor(readonly status: number) {
		super(`systems/global.json: ${status}`);
	}
}

/** An answer that asking again will not change: the file is not there to be
 *  had. A timeout or a request turned away for now is asked for again. */
const permanent = (e: unknown) =>
	e instanceof StatusError &&
	e.status >= 400 &&
	e.status < 500 &&
	e.status !== 408 &&
	e.status !== 429;

export function loadSystemsGlobal(): Promise<void> {
	if (loadPromise) return loadPromise;
	const p = (async () => {
		const r = await fetchWithTimeout(`${dataBase()}/v1/systems/global.json`);
		if (!r.ok) throw new StatusError(r.status);
		const raw = (await r.json()) as {
			gm?: Record<string, number>;
			nut_prec_angles?: Record<string, number[]>;
			nut_prec_phase_degree?: Record<string, number>;
		};
		if (raw.gm) {
			for (const [k, v] of Object.entries(raw.gm)) gmKm3s2.set(parseInt(k, 10), v);
		}
		if (raw.nut_prec_angles) {
			for (const [k, v] of Object.entries(raw.nut_prec_angles)) {
				// SPICE's default when the kernel sets no MAX_PHASE_DEGREE.
				const phaseDegree = raw.nut_prec_phase_degree?.[k] ?? 1;
				phases.set(parseInt(k, 10), { angles: v, phaseDegree });
			}
		}
		loaded = true;
	})();
	p.then(
		() => {
			retry.clear(RETRY_KEY);
			settle();
		},
		(e) => {
			// Forgotten on any failure, an error status included, so the next
			// caller fetches again: the GMs and nutation angles would be missing
			// all session.
			if (loadPromise === p) loadPromise = null;
			if (!permanent(e)) {
				retry.fail(RETRY_KEY);
				return;
			}
			absent = true;
			retry.clear(RETRY_KEY);
			settle();
		}
	);
	loadPromise = p;
	return p;
}

/** Tell the listeners the file has loaded, or will not. One that throws does
 *  not keep the others from being told. */
function settle(): void {
	const told = [...listeners];
	listeners.clear();
	for (const listener of told) {
		try {
			listener();
		} catch (e) {
			console.error('systems-global: a listener failed:', e);
		}
	}
}

/**
 * Tell `listener` once global.json has loaded, or the data host has said it
 * has none: at once if either is so. The scene loads the file once at boot and
 * goes on without it, and every moon then spins without its nutation terms.
 * So for as long as someone listens, it is asked for again, waiting longer
 * after each failure, and for the line to come back while it is down.
 * Returns what stops `listener` being told.
 */
export function onSystemsGlobalSettled(listener: () => void): () => void {
	if (loaded || absent) {
		listener();
		return () => {};
	}
	listeners.add(listener);
	void askAgain();
	return () => listeners.delete(listener);
}

async function askAgain(): Promise<void> {
	// A failure is waited out first: the backoff asks again when it is over.
	if (loaded || absent || listeners.size === 0 || retry.waiting(RETRY_KEY)) return;
	await untilOnline();
	if (listeners.size === 0) return;
	await loadSystemsGlobal().catch(() => {});
}

/** Whether the sums of body `id` wait on the angles of a global.json that
 *  has not loaded. Its spin is off by its nutation terms till it does:
 *  Mimas's by 45° in 2026. */
export function nutPrecAwaited(id: string, sums: NutPrecSums | undefined): sums is NutPrecSums {
	return !!sums && !loaded && !absent && naifId(id) !== null;
}

/** The nutation terms of body `id`: its own sums joined with the angles its
 *  system shares. Undefined where either is missing. */
export function nutPrecFor(id: string, sums: NutPrecSums | undefined): NutPrec | undefined {
	const naif = naifId(id);
	if (naif === null || !sums) return undefined;
	const owned = phases.get(naif >= 100 ? Math.trunc(naif / 100) : naif);
	return owned && { ...sums, ...owned };
}

export function getGmKm3s2(naifId: number): number | undefined {
	return gmKm3s2.get(naifId);
}
