/**
 * The Solar System minimap: Sun + planets + dwarf planets on a log
 * heliocentric-distance axis at true relative diameters, plus the Main-belt and
 * Kuiper-belt bands. Drives the lineup hero on the Solar System root page.
 * Fetched once and cached (tiny — a few dozen objects).
 */

import { dataBase } from '$lib/fetch/data-base';
import { memoizedGzJson } from '$lib/fetch/gz';

export interface SolarSystemMapObject {
	/** Object.id — routing/focus id and localized-name key. */
	id: string;
	qid: string | null;
	/** English fallback; overridden by the localized name where available. */
	name: string;
	kind: 'star' | 'planet' | 'dwarf' | 'asteroid' | 'moon';
	/** Semi-major axis [AU] — log x position (moons inherit their planet's). */
	a: number;
	/** Inclination to the ecliptic [deg] — vertical offset (0 for moons). */
	i: number;
	diameter_km: number;
	/** Resolved tint for small bodies; null falls back to the shared palette. */
	color: string | null;
	/** Moons: parent planet Object.id — placement anchor + link target. */
	parent?: string;
	/** Moons: true → link to the parent's moons tab; false → focus the moon. */
	link_parent?: boolean;
	/** Ringed planet: ring span as multiples of the planet's equatorial radius. */
	rings?: { inner: number; outer: number };
	/** Planets: total moon count, shown in the moon tooltip ("Jupiter · N moons"). */
	moon_count?: number;
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

export const fetchSolarSystemMap = memoizedGzJson<SolarSystemMapFile>(
	() => `${dataBase()}/v1/groups/__solar_system_map__.json.gz`,
	{ error: (res) => `Failed to fetch solar system map: ${res.status}` }
);
