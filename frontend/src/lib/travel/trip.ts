/**
 * The terms of a trip — everything the planner asks for beyond its two ends —
 * and how they ride in the URL.
 *
 * The ends live in the path (`/nav/<from>/<to>`); the terms live in the query,
 * so a shared link is the trip that was planned rather than the two bodies it
 * joins. Defaults are omitted, so an untouched form adds nothing to the URL.
 *
 * Nothing here imports the travel kernel at runtime — the URL codec is reached
 * on every page load, and the kernel is a chunk only the planner pulls in.
 */

import { dateToJD, jdToDate } from '$lib/format/date';
import type { RouteProfile } from '$lib/math/travel';

/**
 * How a trip meets a body at one end. These are the kernel's own manoeuvre
 * cases, not named orbits — "low-orbit" is a circular parking orbit and
 * "elliptical" the loose capture ellipse a real orbiter enters first.
 */
export type EndpointMode = 'surface' | 'low-orbit' | 'elliptical' | 'flyby';

/** Modes each end can be in. Departure has no elliptical case — the injection
 *  burn is priced from a circular parking orbit — and only a destination can be
 *  flown past. */
export const ORIGIN_MODES: readonly EndpointMode[] = ['surface', 'low-orbit'];
export const TARGET_MODES: readonly EndpointMode[] = [
	'surface',
	'low-orbit',
	'elliptical',
	'flyby'
];

/** When the trip goes: on the app's own clock, or held to a date at one end. */
export type TimeMode = 'now' | 'depart' | 'arrive';
const TIME_MODES: readonly TimeMode[] = ['now', 'depart', 'arrive'];

/**
 * What the route list can offer: the solver's three, a point read off the
 * porkchop by hand, and the arc a drive held all the way flies — which is not a
 * point on the porkchop at all, since every departure date flies the same one.
 */
export type RouteOption = RouteProfile | 'custom' | 'constant-thrust';
const ROUTE_OPTIONS: readonly RouteOption[] = [
	'fast',
	'balanced',
	'efficient',
	'custom',
	'constant-thrust'
];

/** A point read off the porkchop: the departure and the cruise it names. Priced
 *  by the solve it belongs to, so only the two coordinates are state. */
export interface TripPick {
	departJd: number;
	tofDays: number;
}

export interface TripState {
	originMode: EndpointMode;
	targetMode: EndpointMode;
	timeMode: TimeMode;
	/** The date behind the two non-'now' modes, as a JD; null under 'now', which
	 *  searches from the clock. */
	pickedJd: number | null;
	vehicleId: string | null;
	passengers: number;
	payloadKg: number;
	/** Which of the offered trajectories is being read; null before a solve. */
	profile: RouteOption | null;
	pick: TripPick | null;
}

export const DEFAULT_TRIP: TripState = {
	originMode: 'surface',
	targetMode: 'low-orbit',
	timeMode: 'now',
	pickedJd: null,
	vehicleId: null,
	passengers: 0,
	payloadKg: 0,
	profile: null,
	pick: null
};

/** Trailing zeros carry no meaning and make a shared trip harder to read. */
function trim(value: number, digits: number): string {
	return String(Number(value.toFixed(digits)));
}

/**
 * The `&fm=…&when=…` query suffix for a trip's terms, or '' when every one of
 * them is at its default. Always starts with `&` (the view always emits `?at=`),
 * so it is safe to concatenate.
 */
export function serializeTripSuffix(trip: TripState): string {
	const parts: string[] = [];

	if (trip.originMode !== DEFAULT_TRIP.originMode) parts.push(`fm=${trip.originMode}`);
	if (trip.targetMode !== DEFAULT_TRIP.targetMode) parts.push(`tm=${trip.targetMode}`);
	// The date is what the mode means; a mode without one searches the same span
	// "now" does, so it is not a choice worth carrying.
	if (trip.timeMode !== 'now' && trip.pickedJd !== null) {
		parts.push(`when=${trip.timeMode},${jdToDate(trip.pickedJd).toISOString()}`);
	}
	if (trip.vehicleId) parts.push(`craft=${encodeURIComponent(trip.vehicleId)}`);
	if (trip.passengers > 0) parts.push(`crew=${Math.floor(trip.passengers)}`);
	if (trip.payloadKg > 0) parts.push(`cargo=${trim(trip.payloadKg, 3)}`);
	// A solve lands on 'balanced' when nothing has been chosen, so it reads as the
	// absence of a choice rather than as one.
	if (trip.profile !== null && trip.profile !== 'balanced') parts.push(`route=${trip.profile}`);
	if (trip.pick) parts.push(`pick=${trim(trip.pick.departJd, 5)},${trim(trip.pick.tofDays, 4)}`);

	return parts.length ? `&${parts.join('&')}` : '';
}

function parseMode(
	raw: string | null,
	allowed: readonly EndpointMode[],
	fallback: EndpointMode
): EndpointMode {
	return raw !== null && allowed.includes(raw as EndpointMode) ? (raw as EndpointMode) : fallback;
}

/** `when=<mode>,<iso>`. A mode with no usable date falls back to 'now' — the
 *  panel would only re-seed the date from the clock anyway. */
function parseWhen(raw: string | null): Pick<TripState, 'timeMode' | 'pickedJd'> {
	const none = { timeMode: 'now' as const, pickedJd: null };
	if (!raw) return none;

	const comma = raw.indexOf(',');
	if (comma < 0) return none;
	const mode = raw.slice(0, comma) as TimeMode;
	if (mode === 'now' || !TIME_MODES.includes(mode)) return none;

	const date = new Date(raw.slice(comma + 1));
	if (isNaN(date.getTime())) return none;
	return { timeMode: mode, pickedJd: dateToJD(date) };
}

/** A manifest figure. Anything unusable reads as nothing aboard, which is what
 *  an empty form says too. */
function parseAmount(raw: string | null): number {
	if (raw === null) return 0;
	const value = Number(raw);
	return Number.isFinite(value) && value > 0 ? value : 0;
}

function parsePick(raw: string | null): TripPick | null {
	if (!raw) return null;
	const [departRaw, tofRaw] = raw.split(',');
	const departJd = Number(departRaw);
	const tofDays = Number(tofRaw);
	if (!Number.isFinite(departJd) || !Number.isFinite(tofDays) || tofDays <= 0) return null;
	return { departJd, tofDays };
}

/** Read a trip's terms out of a URL's query params. Unknown values fall back to
 *  their default rather than failing the load — a trip with one stale term in it
 *  is still a trip. */
export function parseTrip(params: URLSearchParams): TripState {
	const profile = params.get('route') as RouteOption | null;
	return {
		originMode: parseMode(params.get('fm'), ORIGIN_MODES, DEFAULT_TRIP.originMode),
		targetMode: parseMode(params.get('tm'), TARGET_MODES, DEFAULT_TRIP.targetMode),
		...parseWhen(params.get('when')),
		vehicleId: params.get('craft') || null,
		passengers: Math.floor(parseAmount(params.get('crew'))),
		payloadKg: parseAmount(params.get('cargo')),
		profile: profile !== null && ROUTE_OPTIONS.includes(profile) ? profile : null,
		pick: parsePick(params.get('pick'))
	};
}
