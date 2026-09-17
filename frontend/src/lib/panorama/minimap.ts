/**
 * What the traverse minimap draws: the path split at the clock, the field of
 * view as a wedge on the ground, and a frame that holds the whole traverse.
 */

import type { PanoramaEntry } from '$lib/fetch/objects/object-data';
import type { LonLat } from '$lib/flatmap/geometry';
import { dateToJD } from '$lib/time/jd';

const DEG = Math.PI / 180;

export function entryJd(entry: PanoramaEntry): number {
	return dateToJD(new Date(entry.time));
}

export function lonLatOf(entry: PanoramaEntry): LonLat {
	return { lon: entry.lon, lat: entry.lat };
}

/** The traverse in two runs: what the rover had driven by `jd`, and what was
 *  still ahead. The runs share the point the clock stands on, so the line
 *  changes colour there rather than breaking. */
export function splitPath(
	entries: readonly PanoramaEntry[],
	jd: number
): { past: LonLat[]; future: LonLat[] } {
	let last = -1;
	for (let i = 0; i < entries.length; i++) if (entryJd(entries[i]) <= jd) last = i;
	const past = entries.slice(0, last + 1).map(lonLatOf);
	const future = entries.slice(Math.max(0, last)).map(lonLatOf);
	return { past, future: last < 0 ? entries.map(lonLatOf) : future };
}

/** Whether a panorama knows which way it faces. A sphere built from a
 *  published flat image can sit at any azimuth, so nothing about where it
 *  looks may be drawn for one that does not. */
export function hasHeading(entry: PanoramaEntry): boolean {
	return entry.orientation !== 'unknown' && entry.north_offset_deg !== undefined;
}

/** A wedge from the rover across the ground it is looking at. `reachDeg` is
 *  how far it is drawn in degrees of latitude, far past what a camera sees,
 *  so it still reads at the scale of a whole traverse. */
export function viewWedge(
	entry: PanoramaEntry,
	headingDeg: number,
	fovDeg: number,
	reachDeg: number
): LonLat[] {
	const points: LonLat[] = [lonLatOf(entry)];
	const stretch = 1 / Math.max(0.05, Math.cos(entry.lat * DEG));
	const steps = 8;
	for (let i = 0; i <= steps; i++) {
		const bearing = (headingDeg - fovDeg / 2 + (fovDeg * i) / steps) * DEG;
		points.push({
			lon: entry.lon + reachDeg * Math.sin(bearing) * stretch,
			lat: entry.lat + reachDeg * Math.cos(bearing)
		});
	}
	return points;
}

/** Whether the record covers any ground. A lander took every one of its
 *  panoramas from the same spot, so there is no path to frame — only a place. */
export function hasExtent(entries: readonly PanoramaEntry[]): boolean {
	const first = entries[0];
	return entries.some((e) => e.lat !== first?.lat || e.lon !== first?.lon);
}

export interface Frame {
	centerLon: number;
	centerLat: number;
	/** Longitude and latitude spans the frame must hold, degrees. */
	lonSpan: number;
	latSpan: number;
}

/** The box round every panorama of the traverse, padded so the path never
 *  touches the edge, and never smaller than `minSpanDeg` across. */
export function traverseFrame(
	entries: readonly PanoramaEntry[],
	minSpanDeg: number,
	padding = 1.4
): Frame {
	const lats = entries.map((e) => e.lat);
	const lons = entries.map((e) => e.lon);
	const minLat = Math.min(...lats);
	const maxLat = Math.max(...lats);
	const minLon = Math.min(...lons);
	const maxLon = Math.max(...lons);
	const centerLat = (minLat + maxLat) / 2;
	const stretch = 1 / Math.max(0.05, Math.cos(centerLat * DEG));
	return {
		centerLon: (minLon + maxLon) / 2,
		centerLat,
		lonSpan: Math.max(minSpanDeg * stretch, (maxLon - minLon) * padding),
		latSpan: Math.max(minSpanDeg, (maxLat - minLat) * padding)
	};
}

/** A scale bar for a map at `metresPerPx`: the longest 1, 2 or 5 × 10ⁿ
 *  metres that fits in `maxPx`. */
export function scaleBar(metresPerPx: number, maxPx: number): { metres: number; px: number } {
	const maxMetres = metresPerPx * maxPx;
	const magnitude = 10 ** Math.floor(Math.log10(maxMetres));
	const step = [5, 2, 1].find((s) => s * magnitude <= maxMetres) ?? 1;
	const metres = step * magnitude;
	return { metres, px: metres / metresPerPx };
}
