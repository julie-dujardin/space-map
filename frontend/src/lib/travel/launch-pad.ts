/**
 * Launch pads as places a trip can leave from.
 *
 * A `site-` collection is a whole range rather than a place — the Eastern Range
 * spans Canaveral, Kennedy and the commercial pads, deliberately with no
 * range-level point of its own — but it carries every GCAT place under it with
 * its own pads, each good to metres. So a trip "from Baikonur" really leaves
 * from one of its pads, chosen here.
 *
 * Nothing here is an identity: a pad is a latitude and a longitude, and the
 * collection is only how it was found — see `NavPlace`.
 */

import { fetchGroupDetail } from '$lib/fetch/groups/details';
import type { GcatSite } from '$lib/fetch/groups/details';

/** Slug prefix of the launch-site collections. */
export const LAUNCH_SITE_SLUG_PREFIX = 'site-';

/** One pad, flattened out of the site that holds it. */
export interface LaunchPad {
	/** GCAT launch-point code, e.g. "LC39A" — unique within its site. */
	code: string;
	/** What to call it: the trimmed label the export ships, since GCAT's own
	 *  name repeats the place on every pad of a site. */
	name: string;
	latDeg: number;
	lonDeg: number;
	/** Distinct launches from this pad. Zero is common and real: GCAT names pads
	 *  it has never attributed a launch to. */
	launches: number;
	/** The GCAT place the pad belongs to — Canaveral rather than the range. */
	siteName: string;
}

export function isLaunchSiteSlug(slug: string | null | undefined): boolean {
	return !!slug && slug.startsWith(LAUNCH_SITE_SLUG_PREFIX);
}

/** Every placed pad in a range, busiest first. Pads with no position are left
 *  out — a trip cannot leave from somewhere nobody knows the location of. Ties
 *  break on the code so the order is stable across reloads. */
export function padsOf(sites: readonly GcatSite[] | undefined): LaunchPad[] {
	const pads: LaunchPad[] = [];
	for (const site of sites ?? []) {
		for (const pad of site.pads ?? []) {
			if (!isFinite(pad.lat) || !isFinite(pad.lon)) continue;
			pads.push({
				code: pad.code,
				name: pad.label || pad.name || pad.code,
				latDeg: pad.lat,
				lonDeg: pad.lon,
				launches: pad.launches,
				siteName: site.name || site.code
			});
		}
	}
	return pads.sort((a, b) => b.launches - a.launches || a.code.localeCompare(b.code));
}

/** The range's pads, or an empty list when the collection has none to give. */
export async function fetchLaunchPads(slug: string): Promise<LaunchPad[]> {
	if (!isLaunchSiteSlug(slug)) return [];
	try {
		const detail = await fetchGroupDetail(slug);
		return padsOf(detail.global?.gcat_sites);
	} catch (e) {
		console.warn(`[travel] could not read the pads of ${slug}:`, e);
		return [];
	}
}

/** The pad a trip should leave from by default: the busiest one, since every
 *  other choice is arbitrary in a way this isn't — the pad the place is known
 *  for. Named on screen and swappable, so the choice is offered, not hidden. */
export function busiestPad(pads: readonly LaunchPad[]): LaunchPad | null {
	return pads[0] ?? null;
}

/** How far apart two points may be and still be the same pad, degrees. About a
 *  kilometre, which no two pads in GCAT are closer than. */
const SAME_PAD_DEG = 0.01;

/** Which of these pads a point stands on, or null for none. By code where the
 *  link names one, else by distance — an older link carries only coordinates,
 *  and matching on distance survives the rounding the URL puts them through. */
export function padAt(
	pads: readonly LaunchPad[],
	latDeg: number,
	lonDeg: number,
	code?: string | null
): LaunchPad | null {
	if (code) {
		const named = pads.find((p) => p.code === code);
		if (named) return named;
	}
	let best: LaunchPad | null = null;
	let bestGap = SAME_PAD_DEG;
	for (const pad of pads) {
		const dLat = Math.abs(pad.latDeg - latDeg);
		// Longitudes meet again at the antimeridian, and a pad sits at either edge.
		const dLon = Math.min(Math.abs(pad.lonDeg - lonDeg), 360 - Math.abs(pad.lonDeg - lonDeg));
		const gap = Math.hypot(dLat, dLon * Math.cos((latDeg * Math.PI) / 180));
		if (gap < bestGap) {
			bestGap = gap;
			best = pad;
		}
	}
	return best;
}
