/**
 * Choosing which departures and cruise lengths to search.
 *
 * A porkchop only shows what you point it at, so the bounds matter as much as
 * the solver: too narrow and the cheap window falls outside the grid, too wide
 * and every cell is coarse. Both are derived from the pair's own orbits — one
 * synodic period always contains a window, and the Hohmann time sets the scale
 * of a sensible cruise.
 */

import type { PorkchopOptions, TravelBody } from '$lib/math/travel';
import { hohmannTransferDays, synodicPeriodDays } from '$lib/math/travel';

export type TimeMode = 'now' | 'depart' | 'arrive';

/** Beyond this the grid is too coarse to resolve a window; slow pairs get capped. */
const MAX_SEARCH_DAYS = 3 * 365.25;
const MIN_SEARCH_DAYS = 60;

/** How far either side of a chosen departure date to look. */
const DEPART_AT_SLACK_DAYS = 45;

const MIN_TOF_DAYS = 15;
/** Cruise bounds as multiples of the Hohmann time — fast arcs to slow ones. */
const TOF_MIN_FACTOR = 0.35;
const TOF_MAX_FACTOR = 2.2;

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
}

/**
 * Grid bounds for a search, or null when the pair has no usable orbits.
 *
 * The returned options go straight to `computePorkchop`.
 */
export function searchWindow(request: WindowRequest): PorkchopOptions | null {
	const { origin, target, nowJd, timeMode, pickedJd } = request;

	const hohmann = hohmannTransferDays(origin, target);
	if (hohmann === null || !(hohmann > 0)) return null;

	const synodic = synodicPeriodDays(origin, target);
	const span = clamp(
		synodic !== null && Number.isFinite(synodic) ? synodic : MAX_SEARCH_DAYS,
		MIN_SEARCH_DAYS,
		MAX_SEARCH_DAYS
	);

	let departFromJd = nowJd;
	let departToJd = nowJd + span;
	if (timeMode === 'depart' && pickedJd != null) {
		// Centre on the date, but never search departures already in the past.
		departFromJd = Math.max(nowJd, pickedJd - DEPART_AT_SLACK_DAYS);
		departToJd = pickedJd + DEPART_AT_SLACK_DAYS;
	} else if (timeMode === 'arrive' && pickedJd != null) {
		// Everything that could still land by the deadline: the latest useful
		// departure is the deadline minus the fastest cruise worth flying.
		departToJd = Math.max(nowJd + 1, pickedJd - hohmann * TOF_MIN_FACTOR);
	}
	if (departToJd <= departFromJd) departToJd = departFromJd + MIN_SEARCH_DAYS;

	return {
		departFromJd,
		departToJd,
		tofMinDays: Math.max(MIN_TOF_DAYS, hohmann * TOF_MIN_FACTOR),
		tofMaxDays: Math.max(MIN_TOF_DAYS * 2, hohmann * TOF_MAX_FACTOR),
		departSteps: DEPART_STEPS,
		tofSteps: TOF_STEPS
	};
}

function clamp(value: number, lo: number, hi: number): number {
	return value < lo ? lo : value > hi ? hi : value;
}
