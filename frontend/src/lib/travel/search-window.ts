/**
 * Choosing which departures and cruise lengths to search.
 *
 * A porkchop only shows what you point it at, so the bounds matter as much as
 * the solver: too narrow and the cheap window falls outside the grid, too wide
 * and every cell is coarse. Both are derived from the pair's own orbits — one
 * synodic period always contains a window, and the time it takes to cross
 * between them sets the scale of a sensible cruise.
 */

import type { PorkchopOptions, TravelBody } from '$lib/math/travel';
import { synodicPeriodDays, systemArcBounds, transferScale } from '$lib/math/travel';
import type { TimeMode } from './trip';

/** Beyond this the grid is too coarse to resolve a window; slow pairs get capped. */
const MAX_SEARCH_DAYS = 3 * 365.25;
/**
 * How short the departure axis may get.
 *
 * Every floor below is capped by the pair's own transfer time as well, because a
 * bare day count is a solar-system assumption: Io to Europa is a 1.3-day crossing
 * with a 3.5-day synodic period, and a flat 60-day floor would grid seventeen of
 * them at once and resolve none.
 */
const MIN_SEARCH_DAYS = 60;

/** How far either side of a chosen departure date to look, and at most what share
 *  of the whole span. */
const DEPART_AT_SLACK_DAYS = 45;
const DEPART_AT_SLACK_FRACTION = 0.5;

/** Cruise bounds as multiples of the crossing time — fast arcs to slow ones. */
const TOF_MIN_FACTOR = 0.35;
const TOF_MAX_FACTOR = 2.2;
/**
 * The same bounds for a chase, where the ideal crossing is not the transfer
 * anyone would fly: the target is leaving, so what matters is how fast you can
 * get out there, and the interesting arcs sit far below the Hohmann-like time.
 */
const CHASE_TOF_MIN_FACTOR = 0.06;
const CHASE_TOF_MAX_FACTOR = 1.2;

const DEPART_STEPS = 90;
const TOF_STEPS = 90;

export interface WindowRequest {
	origin: TravelBody;
	target: TravelBody;
	/** Now, on the app's clock. */
	nowJd: number;
	timeMode: TimeMode;
	/** The date behind 'depart' and 'arrive'; ignored under 'now'. */
	pickedJd?: number | null;
	/** Set when the trip stays inside one system — see `RouteOptions`. */
	systemPrimary?: 'departure' | 'target';
	/** μ of the body the transfer orbits, km³/s². Absent means the Sun's — set for
	 *  a pair of moons, where the arc goes round their planet instead. */
	centralMu?: number;
}

/**
 * The grid the fastest and slowest arcs of a same-system transfer both fit in.
 *
 * Nothing here waits for a window: the geometry repeats every time the satellite
 * comes round, and the only thing a departure date changes is how far out it is
 * by then. So the departure axis spans one of its orbits and the cruise axis
 * spans the family.
 */
function systemWindow(request: WindowRequest): PorkchopOptions | null {
	const { origin, target, nowJd, systemPrimary } = request;
	const outbound = systemPrimary === 'departure';
	const primary = outbound ? origin : target;
	const satellite = outbound ? target : origin;
	const orbitDays = satellite.elements.n > 0 ? 360 / satellite.elements.n : MAX_SEARCH_DAYS;
	const departToJd = nowJd + clamp(orbitDays, MIN_SEARCH_DAYS / 4, MAX_SEARCH_DAYS);
	// One orbit of the satellite covers every distance it reaches, so bounds taken
	// across the window bracket every arc the grid can contain.
	const bounds = systemArcBounds(primary, satellite, nowJd, departToJd);
	if (!bounds || !(bounds.slowestDays > 0)) return null;

	return {
		departFromJd: nowJd,
		departToJd,
		tofMinDays: bounds.fastestDays,
		tofMaxDays: bounds.slowestDays,
		departSteps: DEPART_STEPS,
		tofSteps: TOF_STEPS,
		systemPrimary
	};
}

/**
 * Grid bounds for a search, or null when the pair has no usable orbits.
 *
 * The returned options go straight to `computePorkchop`.
 */
export function searchWindow(request: WindowRequest): PorkchopOptions | null {
	const { origin, target, nowJd, timeMode, pickedJd, centralMu } = request;
	if (request.systemPrimary) return systemWindow(request);

	// The Hohmann time where both orbits are round enough for it, and the crossing
	// between the two current distances where they are not. The arcs themselves
	// are still real Lambert solves — only the bounds are approximated.
	const scale = transferScale(origin, target, nowJd, centralMu);
	if (scale === null) return null;
	const { days: crossing, chase } = scale;

	// A target that is leaving has no synodic period worth the name, whatever its
	// mean motion says — nothing about the pair repeats.
	const synodic = chase ? null : synodicPeriodDays(origin, target);
	const span = clamp(
		synodic !== null && Number.isFinite(synodic) ? synodic : MAX_SEARCH_DAYS,
		Math.min(MIN_SEARCH_DAYS, crossing),
		MAX_SEARCH_DAYS
	);
	const tofMinFactor = chase ? CHASE_TOF_MIN_FACTOR : TOF_MIN_FACTOR;
	const tofMaxFactor = chase ? CHASE_TOF_MAX_FACTOR : TOF_MAX_FACTOR;

	let departFromJd = nowJd;
	let departToJd = nowJd + span;
	if (timeMode === 'depart' && pickedJd != null) {
		// Centre on the date, but never search departures already in the past.
		const slack = Math.min(DEPART_AT_SLACK_DAYS, span * DEPART_AT_SLACK_FRACTION);
		departFromJd = Math.max(nowJd, pickedJd - slack);
		departToJd = pickedJd + slack;
	} else if (timeMode === 'arrive' && pickedJd != null) {
		// Everything that could still land by the deadline: the latest useful
		// departure is the deadline minus the fastest cruise worth flying.
		departToJd = pickedJd - crossing * tofMinFactor;
	}
	// A deadline already past leaves nothing to search; fall back to the open span.
	if (departToJd <= departFromJd) departToJd = departFromJd + span;

	return {
		departFromJd,
		departToJd,
		tofMinDays: crossing * tofMinFactor,
		tofMaxDays: crossing * tofMaxFactor,
		departSteps: DEPART_STEPS,
		tofSteps: TOF_STEPS,
		centralMu
	};
}

function clamp(value: number, lo: number, hi: number): number {
	return value < lo ? lo : value > hi ? hi : value;
}
