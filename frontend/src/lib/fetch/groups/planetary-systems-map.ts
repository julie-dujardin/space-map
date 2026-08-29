/**
 * Baked minimaps of every planetary system, for the Planetary Systems
 * collection's tiles: the system page draws its map from the live scene, which
 * only holds the active system's moons. Fetched once and cached.
 */

import { DATA_BASE } from '$lib/fetch/data-base';

export interface PlanetarySystemsMapMoon {
	id: string;
	/** Semi-major axis in primary equatorial radii. */
	a_rp: number;
	/** Orbit tilt to the primary's equator [deg]; > 90 is retrograde. */
	tilt_deg: number;
	/** 0 → designation-only, drawn at the floor. */
	radius_km: number;
	color?: string;
}

export interface PlanetarySystemsMapEntry {
	primary: { id: string; radius_km: number };
	moons: PlanetarySystemsMapMoon[];
	rings: { inner_rp: number; outer_rp: number } | null;
	moon_count: number;
}

/** Keyed by barycenter id. */
export type PlanetarySystemsMapFile = Record<string, PlanetarySystemsMapEntry>;

let pending: Promise<PlanetarySystemsMapFile> | null = null;

export function fetchPlanetarySystemsMap(): Promise<PlanetarySystemsMapFile> {
	if (pending) return pending;
	pending = (async () => {
		const res = await fetch(`${DATA_BASE}/v1/groups/__planetary_systems_map__.json.gz`);
		if (!res.ok) throw new Error(`Failed to fetch planetary systems map: ${res.status}`);
		const ds = new DecompressionStream('gzip');
		return (await new Response(res.body!.pipeThrough(ds)).json()) as PlanetarySystemsMapFile;
	})();
	return pending;
}
