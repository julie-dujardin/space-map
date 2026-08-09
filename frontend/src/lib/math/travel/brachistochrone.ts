/**
 * The arc a drive that never stops flies.
 *
 * A torch ship does not transfer between orbits. It points at where the
 * destination will be, burns until halfway, flips, and burns the rest of the way
 * down — a brachistochrone, whose only parameter is how hard the drive pushes.
 * Nothing about it is a launch window: every departure date flies the same arc,
 * which is exactly what makes these ships feel like ships.
 *
 * Distance and duration are tangled, since the destination moves while you cross
 * to it, so the arrival is solved for rather than assumed.
 *
 * Two approximations, both deliberate. Gravity is left out of the crossing
 * itself: at the accelerations this exists for, the Sun's pull over the arc is a
 * rounding error against the drive's own, and the two wells that do matter are
 * priced at the ends by the same manoeuvre model every other route uses. And the
 * arc is rest-to-rest in the frame it is flown in, so the ship arrives still
 * carrying the difference between the two bodies' orbital velocities and pays an
 * ordinary capture for it — invisible to a torch that spent a thousand km/s
 * getting there, and most of the budget for a drive slow enough to be
 * recognisable.
 */

import type { TravelBody } from './body';
import { GM_SUN_KM3_S2, SEC_PER_DAY } from './constants';
import { arrivalCost, departureCost } from './maneuvers';
import type { Route, RouteLeg, RouteOptions } from './route';
import { elementsToState, type StateVector } from './state';
import { relativeState } from './system-transfer';
import { add, norm, normalize, scale, sub, type Vec3 } from './vec3';

/** The primary of a same-system trip, which sits at the centre of its own frame. */
const AT_REST: StateVector = { r: [0, 0, 0], v: [0, 0, 0], mu: 0 };

/** Where each end of the trip is, in whatever frame the crossing is flown in. */
type Ephemeris = (jd: number) => StateVector | null;

function frameEnds(
	departure: TravelBody,
	target: TravelBody,
	systemPrimary: RouteOptions['systemPrimary'],
	centralMu: number
): { from: Ephemeris; to: Ephemeris } {
	if (systemPrimary === 'departure') {
		return { from: () => AT_REST, to: (jd) => relativeState(target, departure, jd) };
	}
	if (systemPrimary === 'target') {
		return { from: (jd) => relativeState(departure, target, jd), to: () => AT_REST };
	}
	return {
		from: (jd) => elementsToState(departure.elements, jd, centralMu),
		to: (jd) => elementsToState(target.elements, jd, centralMu)
	};
}

/**
 * How far the burn reaches in `seconds`, as a multiple of `a·t²`.
 *
 * A quarter for the ordinary flip — half the time spent stopping covers half as
 * much ground — and a half when there is nothing to stop for.
 */
const REACH_WITH_FLIP = 1 / 4;
const REACH_STRAIGHT_THROUGH = 1 / 2;

/**
 * Steps the bracket search takes, and how far past the still-target estimate it
 * keeps looking. A destination that runs away faster than the drive closes has
 * no arc at all, and the search has to be able to say so rather than climb
 * forever.
 */
const BRACKET_STEPS = 64;
const BRACKET_SPAN = 32;
/** Halvings of the bracket. Forty takes any of these to under a second, which is
 *  finer than the elements the ends are placed by. */
const BISECTION_STEPS = 40;

/**
 * The first duration at which the burn reaches its destination, in seconds.
 *
 * `shortfall` is negative while the arc falls short and positive once it
 * overshoots, so the crossing is its first root. Scanned rather than iterated to
 * a fixed point: the destination's own motion feeds back into the answer hard
 * enough that the obvious iteration diverges for any drive slow enough to let it
 * move — which is exactly the interesting case.
 */
function crossingSeconds(
	shortfall: (seconds: number) => number | null,
	guess: number
): number | null {
	const step = (guess * BRACKET_SPAN) / BRACKET_STEPS;
	let lo = 0;
	let hi = 0;
	let bracketed = false;
	for (let i = 1; i <= BRACKET_STEPS; i++) {
		const t = i * step;
		const value = shortfall(t);
		if (value === null) return null;
		if (value >= 0) {
			lo = (i - 1) * step;
			hi = t;
			bracketed = true;
			break;
		}
	}
	if (!bracketed) return null;

	for (let i = 0; i < BISECTION_STEPS; i++) {
		const mid = (lo + hi) / 2;
		const value = shortfall(mid);
		if (value === null) return null;
		if (value >= 0) hi = mid;
		else lo = mid;
	}
	return hi;
}

/**
 * Build the constant-thrust arc leaving at `departJd` under `accelMs2`.
 *
 * Returns null when either end cannot be placed, or when the destination
 * outruns the drive — a metre per second squared does not catch an interstellar
 * comet.
 */
export function buildConstantThrustRoute(
	departure: TravelBody,
	target: TravelBody,
	departJd: number,
	accelMs2: number,
	options: RouteOptions = {}
): Route | null {
	const {
		departureMode = 'surface',
		arrivalMode = 'capture',
		centralMu = GM_SUN_KM3_S2,
		systemPrimary
	} = options;

	const accelKmS2 = accelMs2 / 1000;
	if (!(accelKmS2 > 0)) return null;

	const { from, to } = frameEnds(departure, target, systemPrimary, centralMu);
	const start = from(departJd);
	const here = to(departJd);
	if (!start || !here) return null;

	const separation = norm(sub(here.r, start.r));
	if (!(separation > 0)) return null;

	// Nothing to slow down for at a flyby, so the drive never flips: the ship
	// crosses on one burn and keeps everything it built up.
	const flips = arrivalMode !== 'flyby';
	const reach = flips ? REACH_WITH_FLIP : REACH_STRAIGHT_THROUGH;

	const shortfall = (seconds: number): number | null => {
		const end = to(departJd + seconds / SEC_PER_DAY);
		if (!end) return null;
		return reach * accelKmS2 * seconds * seconds - norm(sub(end.r, start.r));
	};

	const seconds = crossingSeconds(shortfall, Math.sqrt(separation / (reach * accelKmS2)));
	if (seconds === null || !(seconds > 0)) return null;

	const tofDays = seconds / SEC_PER_DAY;
	const arriveJd = departJd + tofDays;
	const end = to(arriveJd);
	if (!end) return null;

	// Everything the drive spends between the two wells, and the speed it is
	// doing when it stops spending it.
	const cruiseDvKms = accelKmS2 * seconds;
	const peakSpeedKms = flips ? cruiseDvKms / 2 : cruiseDvKms;

	const arrivalVelocity: Vec3 = flips
		? start.v
		: add(start.v, scale(normalize(sub(end.r, start.r)), cruiseDvKms));
	const vInfArrKms = norm(sub(arrivalVelocity, end.v));
	if (!isFinite(vInfArrKms)) return null;

	// Both wells are cleared at zero excess speed: the crossing does not start
	// until the ship is out of one and is over once it is falling into the other.
	const dep = departureCost(departure, 0, departureMode);
	const arr = arrivalCost(target, vInfArrKms, arrivalMode);

	const legs: RouteLeg[] = [];
	if (dep.ascentKms > 0) legs.push({ kind: 'ascent', dvKms: dep.ascentKms, days: 0 });
	legs.push({ kind: 'injection', dvKms: dep.injectionKms, days: 0 });
	legs.push({ kind: 'boost', dvKms: peakSpeedKms, days: tofDays / (flips ? 2 : 1) });
	if (flips) legs.push({ kind: 'brake', dvKms: peakSpeedKms, days: tofDays / 2 });
	if (arrivalMode !== 'flyby') {
		legs.push({ kind: 'capture', dvKms: arr.captureKms, days: 0, aerobraked: arr.aerobraked });
	}
	if (arr.descentKms > 0) {
		legs.push({ kind: 'descent', dvKms: arr.descentKms, days: 0, aerobraked: arr.aerobraked });
	}

	const totalDvKms = legs.reduce((sum, leg) => sum + leg.dvKms, 0);
	if (!isFinite(totalDvKms)) return null;

	return {
		departureId: departure.id,
		targetId: target.id,
		departJd,
		arriveJd,
		tofDays,
		legs,
		totalDvKms,
		inSpaceDvKms: totalDvKms - dep.ascentKms,
		// Leaving at exactly escape speed and no more, which is what C3 measures.
		c3Km2S2: 0,
		vInfDepKms: 0,
		vInfArrKms,
		departureMode,
		arrivalMode,
		constantThrust: accelMs2
	};
}
