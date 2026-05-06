/**
 * Global IAU nutation/precession angles, fetched once at app start from
 * `/data/v1/position/nut_prec_angles.json`. Indexed by owner naif_id (the
 * planetary system barycenter — for any body, owner = `naif_id // 100` if
 * `naif_id ≥ 100`, else `naif_id`). The same angles are shared by every body
 * in the system.
 */

import { DATA_BASE } from './data-base';

const angles = new Map<number, number[]>();
let loadPromise: Promise<void> | null = null;

export function loadNutPrecAngles(): Promise<void> {
	if (loadPromise) return loadPromise;
	loadPromise = (async () => {
		const r = await fetch(`${DATA_BASE}/v1/position/nut_prec_angles.json`);
		if (!r.ok) return;
		const raw = (await r.json()) as Record<string, number[]>;
		for (const [k, v] of Object.entries(raw)) angles.set(parseInt(k, 10), v);
	})();
	return loadPromise;
}

export function ownerIdFor(naifId: number): number {
	return naifId >= 100 ? Math.trunc(naifId / 100) : naifId;
}

export function getNutPrecAngles(ownerId: number): number[] | undefined {
	return angles.get(ownerId);
}
