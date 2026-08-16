/**
 * Always-loaded systems metadata from `/data/v1/systems/global.json`,
 * distinct from the lazily-loaded per-system `systems/naif-{N}.json`. Holds
 * two context-independent lookups: GMs (km^3/s^2 per NAIF id, from SPICE PCK
 * kernels, plus a synthesized SSB row reusing the Sun's GM) for chebyshev
 * trail-buffer period estimates, and NUT_PREC_ANGLES (IAU nutation/precession
 * coefficients per planetary-system owner) paired with each body's
 * `nut_prec` array to evaluate pole/spin orientation.
 */

import { DATA_BASE } from './data-base';
import { fetchWithTimeout } from './fetch-timeout';

const angles = new Map<number, number[]>();
const gmKm3s2 = new Map<number, number>();
let loadPromise: Promise<void> | null = null;

export function loadSystemsGlobal(): Promise<void> {
	if (loadPromise) return loadPromise;
	const p = (async () => {
		const r = await fetchWithTimeout(`${DATA_BASE}/v1/systems/global.json`);
		if (!r.ok) return;
		const raw = (await r.json()) as {
			gm?: Record<string, number>;
			nut_prec_angles?: Record<string, number[]>;
		};
		if (raw.gm) {
			for (const [k, v] of Object.entries(raw.gm)) gmKm3s2.set(parseInt(k, 10), v);
		}
		if (raw.nut_prec_angles) {
			for (const [k, v] of Object.entries(raw.nut_prec_angles)) angles.set(parseInt(k, 10), v);
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

export function getNutPrecAngles(ownerId: number): number[] | undefined {
	return angles.get(ownerId);
}

export function getGmKm3s2(naifId: number): number | undefined {
	return gmKm3s2.get(naifId);
}
