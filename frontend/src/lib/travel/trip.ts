/**
 * The terms of a trip — everything the planner asks for beyond its two ends —
 * and how they ride in the URL.
 *
 * The ends live in the path (`/nav/<from>/<to>`); the terms live in the query,
 * so a shared link is the trip that was planned, not just the two bodies it
 * joins. Defaults are omitted, so an untouched form adds nothing to the URL.
 *
 * Nothing here imports the travel kernel at runtime — the URL codec is reached
 * on every page load, and the kernel is a chunk only the planner pulls in.
 */

import { dateToJD, jdToDate } from '$lib/format/date';
import type { AeroAssist, RouteProfile } from '$lib/math/travel';

/**
 * How a trip meets a body at one end: the ground, one of the orbits that body
 * can hold, or a pass with no burn at all.
 *
 * Which orbits actually exist is a fact about the body and is derived in
 * `orbits.ts`; this union is only what a link may name. Every value is priced
 * differently by the kernel — an orbit costing the same as another would be a
 * distinction the model can't back.
 */
export type EndpointMode =
	| 'surface'
	| 'low-orbit'
	/** The loose ellipse a capture burn drops into. Named for what it is rather
	 *  than for the burn, and spelled as it always was so old links still read. */
	| 'elliptical'
	| 'semi-sync'
	| 'stationary'
	| 'transfer'
	| 'heo'
	| 'custom'
	| 'flyby';

/** Modes each end can be in. A departure is never a flyby, and never onto a
 *  transfer orbit or a capture ellipse — both are shapes an arrival leaves you
 *  in, not ones you set out from. */
export const ORIGIN_MODES: readonly EndpointMode[] = [
	'surface',
	'low-orbit',
	'semi-sync',
	'stationary',
	'heo',
	'custom'
];
export const TARGET_MODES: readonly EndpointMode[] = [
	'surface',
	'low-orbit',
	'elliptical',
	'semi-sync',
	'stationary',
	'transfer',
	'heo',
	'custom',
	'flyby'
];

/** What to ask of the destination's atmosphere. Only ever offered where there
 *  is one; kept across destination changes so going back to a body with air
 *  restores the trip that was being planned. */
const AERO_ASSISTS: readonly AeroAssist[] = ['none', 'aerocapture', 'aerobraking'];

/** When the trip goes: on the app's own clock, or held to a date at one end. */
export type TimeMode = 'now' | 'depart' | 'arrive';
const TIME_MODES: readonly TimeMode[] = ['now', 'depart', 'arrive'];

/**
 * What the route list can offer: the solver's three, a point read off the
 * porkchop by hand, the arcs a drive held all the way flies, the spiral a
 * drive too weak to burn flies, and a route swinging past a third body. Only
 * the first four are points on the porkchop — a spiral leaves when its phase
 * closes and a swing-by departs years outside the grid — so none of the rest
 * can be named by a `pick=` alone.
 *
 * The held arc is four of them: how long the drive is off in the middle is
 * the same kind of choice a launch window is. `constant-thrust`, the flat-out
 * crossing, keeps its old spelling so old links still read.
 */
export type RouteOption = RouteProfile | 'custom' | TorchOption | 'low-thrust' | 'gravity-assist';
export type TorchOption =
	| 'constant-thrust'
	| 'constant-thrust-balanced'
	| 'constant-thrust-efficient'
	| 'constant-thrust-custom';
const ROUTE_OPTIONS: readonly RouteOption[] = [
	'fast',
	'balanced',
	'efficient',
	'custom',
	'constant-thrust',
	'constant-thrust-balanced',
	'constant-thrust-efficient',
	'constant-thrust-custom',
	'low-thrust',
	'gravity-assist'
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
	/** Altitude of the `custom` orbit at each end, km. Carried whatever the mode
	 *  is, so switching away and back does not lose the altitude that was set. */
	originAltKm: number;
	targetAltKm: number;
	aero: AeroAssist;
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
	/** Where the hand-set constant-thrust arc sits between a flat-out crossing
	 *  (0) and the longest coast the model holds (1). The presets sit at fixed
	 *  points on that span and don't read this. A share rather than a duration:
	 *  how long a coast is on offer is a fact about the pair and the drive, so a
	 *  link carrying days would mean something else for the trip it opened on. */
	coastFraction: number;
}

/** Where a custom orbit starts before it is moved, km. High enough to be
 *  visibly a choice rather than the parking orbit under another name. */
export const DEFAULT_CUSTOM_ALT_KM = 1000;

export const DEFAULT_TRIP: TripState = {
	originMode: 'surface',
	targetMode: 'low-orbit',
	originAltKm: DEFAULT_CUSTOM_ALT_KM,
	targetAltKm: DEFAULT_CUSTOM_ALT_KM,
	// Somewhere with air is somewhere you use the air: arriving at Mars on the
	// engine alone is the unusual choice, and the one worth having to make.
	aero: 'aerocapture',
	timeMode: 'now',
	pickedJd: null,
	vehicleId: null,
	passengers: 0,
	payloadKg: 0,
	profile: null,
	pick: null,
	coastFraction: 0
};

/** Trailing zeros carry no meaning and make a shared trip harder to read. */
function trim(value: number, digits: number): string {
	return String(Number(value.toFixed(digits)));
}

/** The `&fm=…&when=…` query suffix for a trip's terms, or '' when every one of
 *  them is at its default. Always starts with `&` (the view always emits
 *  `?at=`), so it's safe to concatenate. */
export function serializeTripSuffix(trip: TripState): string {
	const parts: string[] = [];

	if (trip.originMode !== DEFAULT_TRIP.originMode) parts.push(`fm=${trip.originMode}`);
	if (trip.targetMode !== DEFAULT_TRIP.targetMode) parts.push(`tm=${trip.targetMode}`);
	// Only carried by the mode that means anything by it.
	if (trip.originMode === 'custom') parts.push(`falt=${trim(trip.originAltKm, 1)}`);
	if (trip.targetMode === 'custom') parts.push(`talt=${trim(trip.targetAltKm, 1)}`);
	if (trip.aero !== DEFAULT_TRIP.aero) parts.push(`aero=${trip.aero}`);
	// The date is what the mode means; a mode without one searches the same span
	// "now" does, so it is not a choice worth carrying.
	if (trip.timeMode !== 'now' && trip.pickedJd !== null) {
		parts.push(`when=${trip.timeMode},${jdToDate(trip.pickedJd).toISOString()}`);
	}
	if (trip.vehicleId) parts.push(`craft=${encodeURIComponent(trip.vehicleId)}`);
	if (trip.passengers > 0) parts.push(`crew=${Math.floor(trip.passengers)}`);
	if (trip.payloadKg > 0) parts.push(`cargo=${trim(trip.payloadKg, 3)}`);
	// Every named trajectory is written, 'balanced' included: a route is chosen
	// rather than settled on, and its absence says the trip is still being
	// chosen between rather than read.
	if (trip.profile !== null) parts.push(`route=${trip.profile}`);
	if (trip.pick) parts.push(`pick=${trim(trip.pick.departJd, 5)},${trim(trip.pick.tofDays, 4)}`);
	// Only ever means anything alongside a constant-thrust arc, but it's carried
	// whenever it's been moved: the craft that flies one is in the link too, and
	// dropping the coast would hand back the flat-out crossing instead.
	if (trip.coastFraction > 0) parts.push(`coast=${trim(trip.coastFraction, 3)}`);

	return parts.length ? `&${parts.join('&')}` : '';
}

function parseMode(
	raw: string | null,
	allowed: readonly EndpointMode[],
	fallback: EndpointMode
): EndpointMode {
	return raw !== null && allowed.includes(raw as EndpointMode) ? (raw as EndpointMode) : fallback;
}

/** `when=<mode>,<iso>`. A mode with no usable date falls back to 'now': the
 *  panel would only re-seed it from the clock anyway. */
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

/** A custom orbit's altitude. Anything unusable falls back to the default rather
 *  than to the surface, which is not an orbit. */
function parseAltitude(raw: string | null): number {
	const value = Number(raw);
	return raw !== null && Number.isFinite(value) && value > 0 ? value : DEFAULT_CUSTOM_ALT_KM;
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

/** A share of the coast on offer. Clamped rather than dropped: a link asking
 *  for more coast than the model has is asking for all of it. */
function parseFraction(raw: string | null): number {
	const value = Number(raw);
	if (raw === null || !Number.isFinite(value)) return 0;
	return Math.min(Math.max(value, 0), 1);
}

/** Read a trip's terms out of a URL's query params. Unknown values fall back
 *  to their default rather than failing the load — a trip with one stale term
 *  is still a trip. */
export function parseTrip(params: URLSearchParams): TripState {
	const profile = params.get('route') as RouteOption | null;
	const aero = params.get('aero') as AeroAssist | null;
	return {
		originMode: parseMode(params.get('fm'), ORIGIN_MODES, DEFAULT_TRIP.originMode),
		targetMode: parseMode(params.get('tm'), TARGET_MODES, DEFAULT_TRIP.targetMode),
		originAltKm: parseAltitude(params.get('falt')),
		targetAltKm: parseAltitude(params.get('talt')),
		aero: aero !== null && AERO_ASSISTS.includes(aero) ? aero : DEFAULT_TRIP.aero,
		...parseWhen(params.get('when')),
		vehicleId: params.get('craft') || null,
		passengers: Math.floor(parseAmount(params.get('crew'))),
		payloadKg: parseAmount(params.get('cargo')),
		profile: profile !== null && ROUTE_OPTIONS.includes(profile) ? profile : null,
		pick: parsePick(params.get('pick')),
		coastFraction: parseFraction(params.get('coast'))
	};
}
