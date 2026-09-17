/**
 * Where a panorama sits on its traverse: the product id that names it, the
 * neighbours it steps to, and the ground-track bearing and distance to each.
 */

import type { PanoramaEntry } from '$lib/fetch/objects/object-data';
import { angularDistance } from '$lib/flatmap/geometry';

/** The product id, which names one panorama and no other. A stop held for
 *  days leaves several mosaics sharing a time and a place, so the time and
 *  place together do not. */
export function panoramaAt(entry: PanoramaEntry): string {
	return entry.id;
}

/** `<time>,<lat>,<lon>`, the key links used before product ids named them. */
function legacyAt(entry: PanoramaEntry): string {
	return `${entry.time},${entry.lat},${entry.lon}`;
}

export function findPanorama(entries: PanoramaEntry[], at: string | null): PanoramaEntry | null {
	if (!at) return null;
	// A shared link outlives the key it was written with, and the old key can
	// name several panoramas, so it lands on the first of them.
	return entries.find((e) => panoramaAt(e) === at || legacyAt(e) === at) ?? null;
}

export interface Neighbour {
	entry: PanoramaEntry;
	/** Ground distance from the current panorama, metres. */
	distanceM: number;
	/** Initial bearing to it, degrees clockwise from north. */
	bearingDeg: number;
}

export interface Neighbours {
	previous: Neighbour | null;
	next: Neighbour | null;
}

/** The entries before and after `current` on the same mission's traverse.
 *  The list is already mission-then-time ordered, so neighbours are adjacent
 *  rows until the mission changes. */
export function neighboursOf(
	entries: PanoramaEntry[],
	current: PanoramaEntry,
	radiusKm: number
): Neighbours {
	const i = entries.findIndex((e) => e.id === current.id);
	const sameMission = (e: PanoramaEntry | undefined) => e && e.mission === current.mission;
	const toNeighbour = (e: PanoramaEntry | undefined): Neighbour | null =>
		sameMission(e)
			? {
					entry: e!,
					distanceM: groundDistanceM(current, e!, radiusKm),
					bearingDeg: bearingDeg(current, e!)
				}
			: null;
	return { previous: toNeighbour(entries[i - 1]), next: toNeighbour(entries[i + 1]) };
}

const DEG = Math.PI / 180;

/** Great-circle distance on a sphere of `radiusKm`, in metres. Rover steps
 *  are metres on a body thousands of kilometres across, so the ellipsoid's
 *  flattening changes nothing a reader would see. */
export function groundDistanceM(a: PanoramaEntry, b: PanoramaEntry, radiusKm: number): number {
	return angularDistance(a, b) * DEG * radiusKm * 1000;
}

/** Initial great-circle bearing from `a` to `b`, degrees clockwise from
 *  north; east-positive longitudes as the export lists them. */
export function bearingDeg(a: PanoramaEntry, b: PanoramaEntry): number {
	const lat1 = a.lat * DEG;
	const lat2 = b.lat * DEG;
	const dLon = (b.lon - a.lon) * DEG;
	const y = Math.sin(dLon) * Math.cos(lat2);
	const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
	return (((Math.atan2(y, x) / DEG) % 360) + 360) % 360;
}

/** Where to look first: the middle of a partial sweep, else north. */
export function initialHeadingDeg(entry: PanoramaEntry): number {
	if (entry.azimuth_start_deg === undefined || entry.hfov_deg === undefined || entry.hfov_deg > 300)
		return 0;
	return (entry.azimuth_start_deg + entry.hfov_deg / 2 - (entry.north_offset_deg ?? 0) + 360) % 360;
}
