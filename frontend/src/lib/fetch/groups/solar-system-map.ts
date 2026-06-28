/**
 * The Solar System minimap: Sun + planets + dwarf planets on a log
 * heliocentric-distance axis at true relative diameters, plus the Main-belt and
 * Kuiper-belt bands. Drives the lineup hero on the Solar System root page.
 * Fetched once and cached (tiny — a few dozen objects).
 */

import { DATA_BASE } from '$lib/fetch/data-base';

export interface SolarSystemMapObject {
	/** Object.id — routing/focus id and localized-name key. */
	id: string;
	qid: string | null;
	/** English fallback; overridden by the localized name where available. */
	name: string;
	kind: 'star' | 'planet' | 'dwarf' | 'asteroid';
	/** Semi-major axis [AU] — log x position. */
	a: number;
	/** Inclination to the ecliptic [deg] — vertical offset. */
	i: number;
	diameter_km: number;
	/** Resolved tint for small bodies; null falls back to the shared palette. */
	color: string | null;
}

export interface SolarSystemMapBelt {
	/** Linked group slug (class-MBA / class-TNO). */
	slug: string;
	label: string;
	kind: 'asteroid_belt' | 'kuiper_belt';
	inner_au: number;
	outer_au: number;
}

export interface SolarSystemMapFile {
	objects: SolarSystemMapObject[];
	belts: SolarSystemMapBelt[];
}

let pending: Promise<SolarSystemMapFile> | null = null;

export function fetchSolarSystemMap(): Promise<SolarSystemMapFile> {
	if (pending) return pending;
	pending = (async () => {
		const res = await fetch(`${DATA_BASE}/v1/groups/__solar_system_map__.json.gz`);
		if (!res.ok) throw new Error(`Failed to fetch solar system map: ${res.status}`);
		const ds = new DecompressionStream('gzip');
		return (await new Response(res.body!.pipeThrough(ds)).json()) as SolarSystemMapFile;
	})();
	return pending;
}
