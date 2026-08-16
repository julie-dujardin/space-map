/**
 * Launch pads as places a trip can leave from.
 *
 * A `site-` collection is a whole range rather than a place — the Eastern Range
 * spans Canaveral, Kennedy and the commercial pads, and its export carries no
 * range-level point on purpose. What it does carry is every GCAT place under it
 * with its own pads, each good to metres. So a trip leaving "from Baikonur"
 * really leaves from one of its pads, and this is where that one is chosen.
 *
 * Nothing here is an identity. A pad is a latitude and a longitude, and the
 * collection is only how they were found — see `NavPlace`.
 */

import { fetchGroupDetail } from '$lib/fetch/groups/details';
import type { GcatPad, GcatSite } from '$lib/fetch/groups/details';

/** Slug prefix of the launch-site collections. */
export const LAUNCH_SITE_SLUG_PREFIX = 'site-';

/** One pad, flattened out of the site that holds it. */
export interface LaunchPad {
	/** GCAT launch-point code, e.g. "LC39A" — unique within its site. */
	code: string;
	/** The pad's own name, as GCAT gives it. */
	name: string;
	latDeg: number;
	lonDeg: number;
	/** Distinct launches from this pad. Zero is common and real: GCAT names pads
	 *  it has never attributed a launch to. */
	launches: number;
	/** The GCAT place the pad belongs to — Canaveral rather than the range. */
	siteName: string;
}

/**
 * A pad's name with the place it sits in trimmed off its tail.
 *
 * GCAT trails every pad's name with where it is, which whatever is showing it
 * already says. How many trailing parts that is varies, so take whatever every
 * pad of the site shares rather than assume a depth: Canaveral's all end
 * ", Cape Canaveral", Baikonur's ", GIK-5, Baykonur, Kazakstan". Keeping only
 * the first part instead would read "LC200/39 · PU39" at Baikonur, where GCAT
 * leads with the launcher and names the pad second.
 */
export function padLabels(pads: readonly GcatPad[]): Map<string, string> {
	const parts = pads.map((p) => p.name.split(',').map((s) => s.trim()));
	// Majority, not unanimity: Baikonur has one oddly-punctuated row
	// ("Buran runway, GIK-5 Baykonur") that shares no tail with the other
	// 120, and requiring agreement would leave the site's name on every row.
	let shared: string[] = [];
	for (let depth = 1; ; depth++) {
		const counts = new Map<string, number>();
		for (const part of parts) {
			// A pad never gives up its whole name, so it stops voting once
			// the tail would consume it.
			if (part.length <= depth) continue;
			// Keyed as JSON so a multi-word part ("Cape Canaveral") stays one, and
			// so no separator byte can end up in the source.
			const tail = JSON.stringify(part.slice(part.length - depth));
			counts.set(tail, (counts.get(tail) ?? 0) + 1);
		}
		const [best, votes] = [...counts].reduce((top, row) => (row[1] > top[1] ? row : top), [
			'',
			0
		] as [string, number]);
		if (votes <= pads.length / 2) break;
		shared = JSON.parse(best);
	}
	return new Map(
		pads.map((p, i) => {
			const own = parts[i];
			const trailing = own.slice(own.length - shared.length);
			const strip =
				shared.length > 0 &&
				own.length > shared.length &&
				trailing.every((s, j) => s === shared[j]);
			return [p.code, (strip ? own.slice(0, own.length - shared.length) : own).join(', ')];
		})
	);
}

export function isLaunchSiteSlug(slug: string | null | undefined): boolean {
	return !!slug && slug.startsWith(LAUNCH_SITE_SLUG_PREFIX);
}

/**
 * Every placed pad in a range, busiest first.
 *
 * Pads with no position are left out rather than shown unplaceable: a trip
 * cannot leave from somewhere nobody knows the location of. Ties break on the
 * code so the order is stable across reloads.
 */
export function padsOf(sites: readonly GcatSite[] | undefined): LaunchPad[] {
	const pads: LaunchPad[] = [];
	for (const site of sites ?? []) {
		// Trimmed per site, before they are pooled: each site trails its own
		// location, so a range spanning several has no tail in common.
		const labels = padLabels(site.pads ?? []);
		for (const pad of site.pads ?? []) {
			if (!isFinite(pad.lat) || !isFinite(pad.lon)) continue;
			pads.push({
				code: pad.code,
				name: labels.get(pad.code) || pad.name || pad.code,
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

/**
 * The pad a trip should leave from by default: the busiest one.
 *
 * Which pad a reader meant is not a question the collection can answer, and
 * every alternative is arbitrary in a way this one is not — the busiest pad is
 * the one the place is known for. It is named on screen and swappable, so the
 * choice is offered rather than made behind their back.
 */
export function busiestPad(pads: readonly LaunchPad[]): LaunchPad | null {
	return pads[0] ?? null;
}

/** How far apart two points may be and still be the same pad, degrees. About a
 *  kilometre, which no two pads in GCAT are closer than. */
const SAME_PAD_DEG = 0.01;

/**
 * Which of these pads a point stands on, or null when it stands on none.
 *
 * The coordinates are the trip's own — a shared link carries nothing else — so
 * naming the end means finding them again in the collection they came from.
 * Matching on distance rather than on an exact equality survives the rounding
 * the URL puts them through.
 */
export function padAt(
	pads: readonly LaunchPad[],
	latDeg: number,
	lonDeg: number
): LaunchPad | null {
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
