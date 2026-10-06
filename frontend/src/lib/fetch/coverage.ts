/**
 * When the map can place an object. The answer comes from the `coverage`
 * block the pipeline writes on each bundle, and from nothing else: a field
 * such as a launch date or an orbit block does not say what the position
 * files hold.
 */

import { fetchMetadata, isDateSegmented, lastCoveredMs, zoneLayers } from '$lib/fetch/metadata';
import { fetchObjectDetail, type GlobalObjectData } from '$lib/fetch/objects/object-data';
import { unixMsToJD } from '$lib/time/jd';

/** A span of dates, in JD. An open side is infinite. */
export type CoverageWindow = [start: number, end: number];

/** An arrival stays this far inside a window (one minute): its last instant
 *  has no sample, and a playing clock must not leave it at once. */
const EDGE_INSET_JD = 1 / 1440;

/** True when the map can place the object at some date. */
export function canBePlaced(global: GlobalObjectData | null | undefined): boolean {
	return (global?.coverage?.windows.length ?? 0) > 0;
}

/** Last date the Earth zone places a satellite at. The open end of a tracked
 *  satellite stops there: the zone grows each day, the bundle does not. */
async function earthZoneEndJd(): Promise<number> {
	const earth = (await fetchMetadata()).position.zones.earth;
	const zoom = earth && zoneLayers(earth).find((l) => isDateSegmented(l.data))?.data;
	return zoom && isDateSegmented(zoom) ? unixMsToJD(lastCoveredMs(zoom)) : Infinity;
}

/** The spans the map can place `id` in, sorted. Empty: it has no place at any date. */
export async function coverageOf(id: string): Promise<CoverageWindow[]> {
	const detail = await fetchObjectDetail(id, false);
	const windows = detail.global?.coverage?.windows ?? [];
	const openEnd = id.startsWith('norad_satcat-') ? await earthZoneEndJd() : Infinity;
	return windows
		.map(([start, end]): CoverageWindow => [start ?? -Infinity, end ?? openEnd])
		.filter(([start, end]) => end > start);
}

/** The date nearest `jd` that a window covers: `jd` itself when one holds it,
 *  else just inside the nearest edge. Null when there is no window. */
export function nearestCoveredJd(windows: CoverageWindow[], jd: number): number | null {
	let best: number | null = null;
	for (const [start, end] of windows) {
		if (jd > start && jd < end) return jd;
		const inset = Math.min(EDGE_INSET_JD, (end - start) / 2);
		const edge = jd <= start ? start + inset : end - inset;
		if (best === null || Math.abs(edge - jd) < Math.abs(best - jd)) best = edge;
	}
	return best;
}
