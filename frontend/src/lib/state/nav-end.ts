/**
 * The grammar of a trip end, on its own.
 *
 * `/nav`'s route guard has to reject an end it could never resolve, and it runs
 * where `$app/state` does not — so this holds nothing but the two strings and
 * their parse. Everything that needs the live page is in `url.ts`, which
 * re-exports what is here.
 */

import type { NavPlace } from './view';

/** Path segment for an end of a trip that has not been chosen. The two ends are
 *  positional, so a destination-only trip needs something in the departure slot
 *  or `/nav/<x>` would read as a departure. */
export const NAV_UNSET = '-';

/** Every id prefix the app addresses a body by. */
const ID_PREFIXES = ['naif-', 'spkid-', 'norad_satcat-', 'probe-', 'extra-'] as const;

/** Whether a string is a well-formed prefixed body id. The nav route takes ids
 *  straight from the path, so it has to reject junk before the renderer is
 *  asked to frame it. */
export function isBodyId(value: string): boolean {
	const prefix = ID_PREFIXES.find((p) => value.startsWith(p));
	if (!prefix) return false;
	return Number.isFinite(Number(value.slice(prefix.length)));
}

/** Separator between a body id and the IAU feature refining it, mirroring the
 *  `/f/` segment of a feature's own page. A body id is `<prefix>-<number>`, so
 *  it can never contain this. */
const FEATURE_INFIX = '-f-';

/**
 * Separator between a body id and a bare point on its surface.
 *
 * A launch pad is not in any gazetteer, so there is no id to name it by — but
 * a latitude and a longitude place it exactly, need no index to resolve, and
 * say the same thing on every body. Which is why an end is allowed to be a
 * point rather than only a thing.
 */
const PLACE_INFIX = '-at-';

/** Decimal places kept on a trip end's coordinates — about a metre, which is
 *  what a launch pad is known to. */
const PLACE_DECIMALS = 5;

function formatPlace(place: NavPlace): string {
	const round = (v: number) => Number(v.toFixed(PLACE_DECIMALS));
	return `${round(place.latDeg)},${round(place.lonDeg)}`;
}

/** A coordinate pair, or null when it is not one — the point stands for a real
 *  spot on a globe, so nothing off the globe may pass for one. */
function parsePlace(raw: string): NavPlace | null {
	const [lat, lon, ...rest] = raw.split(',');
	if (rest.length > 0 || lon === undefined) return null;
	const latDeg = Number(lat);
	const lonDeg = Number(lon);
	if (!isFinite(latDeg) || !isFinite(lonDeg)) return null;
	if (Math.abs(latDeg) > 90 || Math.abs(lonDeg) > 360) return null;
	return { latDeg, lonDeg };
}

/** A trip end as parsed out of the path: a body, and at most one of the two
 *  ways of naming a place on it. */
export interface ParsedNavEnd {
	bodyId: string;
	featureId: number | null;
	place: NavPlace | null;
}

/** A trip end as one path segment: a body id, or a body id refined by a place
 *  on it — a named feature, or bare coordinates. The pair is one key, so it
 *  travels as one token rather than half in the path and half in the query. */
export function formatNavEnd(
	bodyId: string,
	featureId: number | null,
	place: NavPlace | null = null
): string {
	if (featureId !== null) return `${bodyId}${FEATURE_INFIX}${featureId}`;
	return place ? `${bodyId}${PLACE_INFIX}${formatPlace(place)}` : bodyId;
}

/** Inverse of formatNavEnd; null for anything that isn't a well-formed end. */
export function parseNavEnd(segment: string): ParsedNavEnd | null {
	const placeCut = segment.indexOf(PLACE_INFIX);
	if (placeCut !== -1) {
		const bodyId = segment.slice(0, placeCut);
		const place = parsePlace(segment.slice(placeCut + PLACE_INFIX.length));
		if (!isBodyId(bodyId) || !place) return null;
		return { bodyId, featureId: null, place };
	}
	const cut = segment.indexOf(FEATURE_INFIX);
	if (cut === -1) {
		return isBodyId(segment) ? { bodyId: segment, featureId: null, place: null } : null;
	}
	const bodyId = segment.slice(0, cut);
	const featureId = Number(segment.slice(cut + FEATURE_INFIX.length));
	if (!isBodyId(bodyId) || !Number.isInteger(featureId) || featureId <= 0) return null;
	return { bodyId, featureId, place: null };
}
