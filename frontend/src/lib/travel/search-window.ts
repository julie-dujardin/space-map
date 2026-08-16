/**
 * Choosing which departures and cruise lengths to search.
 *
 * A porkchop only shows what you point it at, so the bounds matter as much as
 * the solver — too narrow and the cheap window falls outside the grid, too
 * wide and every cell is coarse. Both are derived from the pair's own orbits:
 * one synodic period always contains a window, and the crossing time between
 * them sets the scale of a sensible cruise.
 */

import type { PorkchopOptions, TravelBody } from '$lib/math/travel';
import { synodicPeriodDays, systemArcBounds, transferScale } from '$lib/math/travel';
import type { TimeMode } from './trip';

/** Beyond this the grid is too coarse to resolve a window; slow pairs get capped. */
const MAX_SEARCH_DAYS = 3 * 365.25;
/**
 * How short the departure axis may get.
 *
 * Every floor below is capped by the pair's own transfer time too, because a
 * bare day count is a solar-system assumption: Io to Europa is a 1.3-day
 * crossing with a 3.5-day synodic period, and a flat 60-day floor would grid
 * seventeen of them at once and resolve none.
 */
const MIN_SEARCH_DAYS = 60;

/** How far either side of a chosen departure date to look, and at most what share
 *  of the whole span. */
const DEPART_AT_SLACK_DAYS = 45;
const DEPART_AT_SLACK_FRACTION = 0.5;

/** Cruise bounds as multiples of the crossing time — fast arcs to slow ones. */
const TOF_MIN_FACTOR = 0.35;
const TOF_MAX_FACTOR = 2.2;
/** The same bounds for a chase, where the ideal crossing isn't the transfer
 *  anyone would fly: the target is leaving, so what matters is how fast you
 *  can get out there, and the interesting arcs sit far below the Hohmann-like
 *  time. */
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
	/** Days the trip still owes once the crossing is over — an aerobraking
	 *  campaign, where there is one. Shapes the axes only: the deadline itself
	 *  is carried whole, so a caller that leaves this out gets a grid aimed
	 *  slightly wide rather than a wrong answer. */
	arrivalDays?: number;
	/** Set when the trip stays inside one system — see `RouteOptions`. */
	systemPrimary?: 'departure' | 'target';
	/** μ of the body the transfer orbits, km³/s². Absent means the Sun's — set for
	 *  a pair of moons, where the arc goes round their planet instead. */
	centralMu?: number;
}

/**
 * The grid the fastest and slowest arcs of a same-system transfer both fit in.
 *
 * Nothing here waits for a window: the geometry repeats every time the
 * satellite comes round, and a departure date only changes how far out it is
 * by then. So the departure axis spans one of its orbits and the cruise axis
 * spans the family.
 */
function systemWindow(request: WindowRequest): PorkchopOptions | null {
	const { origin, target, nowJd, timeMode, pickedJd, systemPrimary, arrivalDays = 0 } = request;
	const outbound = systemPrimary === 'departure';
	const primary = outbound ? origin : target;
	const satellite = outbound ? target : origin;
	const orbitDays = satellite.elements.n > 0 ? 360 / satellite.elements.n : MAX_SEARCH_DAYS;
	const deadlineJd = timeMode === 'arrive' && pickedJd != null ? pickedJd : undefined;
	// Departures past the deadline are wasted rows, but a deadline inside the
	// crossing is left to answer itself — the whole axis is one orbit of the
	// satellite, and there's nothing shorter to fall back to.
	const latestArriveJd = deadlineJd != null ? deadlineJd - arrivalDays : Infinity;
	const departToJd = Math.min(
		nowJd + clamp(orbitDays, MIN_SEARCH_DAYS / 4, MAX_SEARCH_DAYS),
		latestArriveJd > nowJd ? latestArriveJd : Infinity
	);
	// One orbit of the satellite covers every distance it reaches, so bounds
	// taken across the window bracket every arc the grid can contain.
	const bounds = systemArcBounds(primary, satellite, nowJd, departToJd);
	if (!bounds || !(bounds.slowestDays > 0)) return null;

	return {
		departFromJd: nowJd,
		departToJd,
		tofMinDays: bounds.fastestDays,
		tofMaxDays: bounds.slowestDays,
		departSteps: DEPART_STEPS,
		tofSteps: TOF_STEPS,
		systemPrimary,
		deadlineJd
	};
}

/**
 * Grid bounds for a search, or null when the pair has no usable orbits.
 *
 * The returned options go straight to `computePorkchop`.
 */
export function searchWindow(request: WindowRequest): PorkchopOptions | null {
	const { origin, target, nowJd, timeMode, pickedJd, centralMu, arrivalDays = 0 } = request;
	if (request.systemPrimary) return systemWindow(request);

	// The Hohmann time where both orbits are round enough for it, else the
	// crossing between the two current distances. The arcs themselves are still
	// real Lambert solves — only the bounds are approximated.
	const scale = transferScale(origin, target, nowJd, centralMu);
	if (scale === null) return null;
	const { days: crossing, chase } = scale;

	// A leaving target has no synodic period worth the name, whatever its mean
	// motion says — nothing about the pair repeats.
	const synodic = chase ? null : synodicPeriodDays(origin, target);
	const span = clamp(
		synodic !== null && Number.isFinite(synodic) ? synodic : MAX_SEARCH_DAYS,
		Math.min(MIN_SEARCH_DAYS, crossing),
		MAX_SEARCH_DAYS
	);
	const tofMinFactor = chase ? CHASE_TOF_MIN_FACTOR : TOF_MIN_FACTOR;
	const tofMaxFactor = chase ? CHASE_TOF_MAX_FACTOR : TOF_MAX_FACTOR;

	const tofMinDays = crossing * tofMinFactor;
	let tofMaxDays = crossing * tofMaxFactor;
	let departFromJd = nowJd;
	let departToJd = nowJd + span;
	let deadlineJd: number | undefined;
	if (timeMode === 'depart' && pickedJd != null) {
		// Centre on the date, but never search departures already in the past.
		const slack = Math.min(DEPART_AT_SLACK_DAYS, span * DEPART_AT_SLACK_FRACTION);
		departFromJd = Math.max(nowJd, pickedJd - slack);
		departToJd = pickedJd + slack;
	} else if (timeMode === 'arrive' && pickedJd != null) {
		deadlineJd = pickedJd;
		// Point the grid at what could still land in time: the latest useful
		// departure is the deadline minus the fastest cruise worth flying, and a
		// cruise outlasting the deadline is a row nothing can use. Both apply only
		// while they leave a grid to search — a deadline too close for the pair is
		// answered by finding nothing, not by searching nothing.
		const latestArriveJd = pickedJd - arrivalDays;
		const latestDepartJd = latestArriveJd - tofMinDays;
		const longestTofDays = latestArriveJd - departFromJd;
		if (latestDepartJd > departFromJd && longestTofDays > tofMinDays) {
			departToJd = latestDepartJd;
			tofMaxDays = Math.min(tofMaxDays, longestTofDays);
		}
	}
	// A departure date already past leaves nothing to search — fall back to the
	// open span.
	if (departToJd <= departFromJd) departToJd = departFromJd + span;

	return {
		departFromJd,
		departToJd,
		tofMinDays,
		tofMaxDays,
		departSteps: DEPART_STEPS,
		tofSteps: TOF_STEPS,
		centralMu,
		deadlineJd
	};
}

function clamp(value: number, lo: number, hi: number): number {
	return value < lo ? lo : value > hi ? hi : value;
}
