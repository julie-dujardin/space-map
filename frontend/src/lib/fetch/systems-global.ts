/**
 * Always-loaded systems metadata from `/data/v1/systems/global.json`. The
 * per-system `systems/naif-{N}.json` files load later. It holds the GM per NAIF
 * id (km³/s², with the Sun's GM for the SSB) for trail-buffer period estimates,
 * and the IAU nutation/precession angles per planetary-system owner. The angles
 * pair with each body's `nut_prec` to give its pole and spin.
 */

import type { NutPrec } from '$lib/math/orientation';
import { dataBase } from './data-base';
import { fetchWithTimeout } from './fetch-timeout';

type NutPrecPhases = Pick<NutPrec, 'angles' | 'phaseDegree'>;

const phases = new Map<number, NutPrecPhases>();
const gmKm3s2 = new Map<number, number>();
let loadPromise: Promise<void> | null = null;

export function loadSystemsGlobal(): Promise<void> {
	if (loadPromise) return loadPromise;
	const p = (async () => {
		const r = await fetchWithTimeout(`${dataBase()}/v1/systems/global.json`);
		if (!r.ok) return;
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
	})();
	// Evict on rejection so a boot-time blip doesn't poison the memo — GM/nutation
	// data would otherwise stay dead all session.
	p.catch(() => {
		if (loadPromise === p) loadPromise = null;
	});
	loadPromise = p;
	return p;
}

export function ownerIdFor(naifId: number): number {
	return naifId >= 100 ? Math.trunc(naifId / 100) : naifId;
}

export function getNutPrecPhases(ownerId: number): NutPrecPhases | undefined {
	return phases.get(ownerId);
}

export function getGmKm3s2(naifId: number): number | undefined {
	return gmKm3s2.get(naifId);
}
