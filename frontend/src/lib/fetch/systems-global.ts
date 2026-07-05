/**
 * Always-loaded systems metadata, fetched once at app start from
 * `/data/v1/systems/global.json`. Distinct from `systems/naif-{N}.json`
 * which loads lazily when the user navigates to a planetary system.
 *
 * Holds two context-independent lookups:
 *
 * - **GMs** — gravitational parameters (km^3/s^2) per body NAIF id, sourced
 *   from SPICE PCK kernels. Used by chebyshev trail-buffer sizing to
 *   estimate orbital periods via Kepler's third law for any parent NAIF id.
 *   Includes a synthesized SSB row (naif 0) reusing the Sun's GM so
 *   chebyshev-only bodies that orbit SSB resolve correctly.
 * - **NUT_PREC_ANGLES** — IAU nutation/precession angle coefficients per
 *   planetary-system owner (`naif_id // 100`, or `naif_id` itself if
 *   `< 100`). Paired with each body's `nut_prec` array (in the per-system
 *   file or in the body's global object detail) to evaluate body-fixed
 *   pole/spin orientation.
 */

import { DATA_BASE } from './data-base';
import { fetchWithTimeout } from './fetch-timeout';

const angles = new Map<number, number[]>();
const gmKm3s2 = new Map<number, number>();
let loadPromise: Promise<void> | null = null;

export function loadSystemsGlobal(): Promise<void> {
	if (loadPromise) return loadPromise;
	loadPromise = (async () => {
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
	return loadPromise;
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
