/**
 * The arc a drive that never stops flies. A torch ship doesn't transfer
 * between orbits — it points at where the destination will be, burns until
 * halfway, flips, and burns the rest of the way down: a brachistochrone, whose
 * only parameter is how hard the drive pushes. No launch window: every
 * departure date flies much the same arc, which is what makes these ships
 * feel like ships.
 *
 * Burning all the way is fastest, not the only option. Cutting the drive
 * between the two burns and coasting buys the same distance for less Δv and a
 * longer trip — the trade real missions make, and the one a torch ship gets to
 * decline. `coastFraction` is where on that trade the arc sits.
 *
 * **Gravity is in the crossing**, not left at its ends: the arc is integrated
 * under the primary's pull from leaving one well to falling into the other;
 * see `held-drive`, which owns the flying and steering. What remains here is
 * pricing — the two wells, the legs, and the requested coast.
 *
 * The straight-line assumption survives as the *seed* the real solve starts
 * from — good for a drive that dwarfs the Sun, poor otherwise, which is why
 * the solve can refuse: a ship that can't outpush its primary gets no arc
 * rather than a plausible number. Both wells clear at zero excess speed, so
 * starting the integration there is the same statement as pricing the well at
 * v∞ = 0.
 */

import type { TravelBody } from './body';
import { GM_SUN_KM3_S2, SEC_PER_DAY } from './constants';
import {
	solveHeldDrive,
	type Ephemeris,
	type HeldDriveArc,
	type HeldDriveProblem
} from './held-drive';
import { arrivalCost, departureCost, surfaceSite } from './maneuvers';
import { arrivalLegs, type Route, type RouteLeg, type RouteOptions } from './route';
import { elementsToState, type StateVector } from './state';
import { relativeState } from './system-transfer';
import { add, norm, normalize, scale, sub } from './vec3';

export type { HeldDriveArc, HeldDriveProblem };

/** The primary of a same-system trip, which sits at the centre of its own frame. */
const AT_REST: StateVector = { r: [0, 0, 0], v: [0, 0, 0], mu: 0 };

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
 * How long a coast the slider's far end asks for, as a multiple of the
 * crossing flown flat out. No modelling limit applies — the coast is a conic
 * walked in closed form, exact however long it runs — so the real limit is
 * geometric: past some length the ship can't be pushed back onto the target
 * and the solve stops closing. Wide enough to reach that for most pairs; the
 * arc just stops being offered beyond it.
 */
const COAST_SPAN = 6;

/**
 * How much of the crossing the primary may bend a coast out of, for trips
 * still flown as a straight line — only trips inside one system, whose frame
 * is centred on the body being left or arrived at. That well is already
 * priced at its own end, so what's left is a gap crossed far above the
 * primary where the straight-line assumption holds; the coast still needs a
 * cap since that part of the model hasn't changed.
 */
const COAST_DRIFT_BUDGET = 0.05;

/**
 * Steps the bracket search takes, and how far past the still-target estimate
 * it keeps looking. A destination outrunning the drive has no arc at all, and
 * the search must say so rather than climb forever.
 */
const BRACKET_STEPS = 64;
const BRACKET_SPAN = 32;
/** Halvings of the bracket. Forty takes any of these to under a second, which is
 *  finer than the elements the ends are placed by. */
const BISECTION_STEPS = 40;

/**
 * The shortest burn that reaches the destination *ignoring gravity*, in
 * seconds. `shortfall` is negative while the arc falls short and positive
 * once it overshoots, so the burn is its first root. Scanned rather than
 * iterated to a fixed point: the destination's own motion feeds back hard
 * enough that the obvious iteration diverges for any drive slow enough to let
 * it move — exactly the interesting case. This is the seed, not the answer,
 * and is closest where gravity matters least.
 */
function seedBurnSeconds(
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

export interface ConstantThrustOptions extends RouteOptions {
	/**
	 * Where between the two crossings the arc sits: 0 flies it flat out, 1 coasts
	 * for as long as the geometry still closes. Anything in between is that share
	 * of the longest coast on offer.
	 */
	coastFraction?: number;
}

/** Everything the caller needs to re-fly a solved arc, for drawing it. */
export interface HeldDriveGeometry {
	problem: HeldDriveProblem;
	arc: HeldDriveArc;
}

/**
 * Solve the arc itself, with no pricing attached — the crossing between the
 * two wells, under gravity. Exported for tests, which need to check the
 * trajectory actually lands on the target rather than take the route's word.
 */
export function solveConstantThrustArc(
	departure: TravelBody,
	target: TravelBody,
	departJd: number,
	accelMs2: number,
	options: ConstantThrustOptions = {}
): HeldDriveGeometry | null {
	const {
		arrivalMode = 'capture',
		centralMu = GM_SUN_KM3_S2,
		systemPrimary,
		coastFraction = 0
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
	const burns = flips ? 2 : 1;

	// μ of whatever the crossing goes round. Under a system primary that body is
	// the frame's own centre and sits at the origin, so the pull it exerts is the
	// one the arc is flown against.
	const mu =
		systemPrimary === 'departure'
			? departure.mu
			: systemPrimary === 'target'
				? target.mu
				: centralMu;

	/**
	 * The straight-line burn length for a given coast, which is what the real
	 * solve starts from. Under a burn of `b` either side of a coast of `c` the
	 * ship covers `a·b·(burns·b/2 + c)` and takes `burns·b + c` doing it.
	 */
	const seedFor = (coastSeconds: number): number | null => {
		const shortfall = (burn: number): number | null => {
			const end = to(departJd + (burns * burn + coastSeconds) / SEC_PER_DAY);
			if (!end) return null;
			return accelKmS2 * burn * ((burns * burn) / 2 + coastSeconds) - norm(sub(end.r, start.r));
		};
		const guess =
			(Math.sqrt(coastSeconds * coastSeconds + (2 * burns * separation) / accelKmS2) -
				coastSeconds) /
			burns;
		return seedBurnSeconds(shortfall, guess);
	};

	if (systemPrimary) {
		return straightLineArc({
			start,
			to,
			departJd,
			accelKmS2,
			flips,
			burns,
			mu,
			separation,
			coastFraction,
			seedFor
		});
	}

	/** The whole problem for one coast length, solved. */
	const attempt = (coastSeconds: number): HeldDriveGeometry | null => {
		const seed = seedFor(coastSeconds);
		if (seed === null || !(seed > 0)) return null;
		const problem: HeldDriveProblem = {
			start,
			target: to,
			departJd,
			accelKmS2,
			coastSeconds,
			flips,
			mu,
			seedBurnSeconds: seed
		};
		const arc = solveHeldDrive(problem);
		return arc ? { problem, arc } : null;
	};

	const flatOutSeed = seedFor(0);
	if (flatOutSeed === null || !(flatOutSeed > 0)) return null;

	const wanted = Math.min(Math.max(coastFraction, 0), 1);
	// The flat-out crossing sets the scale the coast is measured in, so the slider
	// means the same thing whatever the pair and the drive. Taken off the seed
	// rather than off a solved arc: it is only a reference duration, and solving
	// for it would double the cost of every answer to fix a digit nobody reads.
	const asked = wanted * COAST_SPAN * burns * flatOutSeed;
	if (!(asked > 0)) return attempt(0);

	// A coast the geometry cannot absorb is shortened rather than refused: the
	// slider's far end saturates at the longest crossing that still closes rather
	// than taking the arc away.
	for (let coastSeconds = asked; coastSeconds > 1; coastSeconds /= 2) {
		const solved = attempt(coastSeconds);
		if (solved) return solved;
	}
	return attempt(0);
}

/**
 * The old straight-line crossing, kept for trips inside one system. Nothing
 * here is integrated: the ship runs down the chord, and the coast is capped
 * where the primary would bend it out of that line by `COAST_DRIFT_BUDGET` of
 * the distance crossed. The returned arc wears the same shape as a flown one
 * so pricing doesn't need to know which it got, but `thrustDir` is just the
 * chord — nothing should re-fly it.
 */
function straightLineArc(args: {
	start: StateVector;
	to: Ephemeris;
	departJd: number;
	accelKmS2: number;
	flips: boolean;
	burns: number;
	mu: number;
	separation: number;
	coastFraction: number;
	seedFor: (coastSeconds: number) => number | null;
}): HeldDriveGeometry | null {
	const { start, to, departJd, accelKmS2, flips, burns, mu, coastFraction, seedFor } = args;

	const flatOutBurn = seedFor(0);
	if (flatOutBurn === null || !(flatOutBurn > 0)) return null;
	const flatOutEnd = to(departJd + (burns * flatOutBurn) / SEC_PER_DAY);
	if (!flatOutEnd) return null;

	// How deep in the well the crossing runs, as the two ends' own depths. The
	// midpoint of the line would answer the same for most trips and answer zero
	// for a line that passes over the primary.
	const depthKm = (norm(start.r) + norm(flatOutEnd.r)) / 2;
	const pullKmS2 = depthKm > 0 ? mu / (depthKm * depthKm) : Infinity;
	const crossedKm = norm(sub(flatOutEnd.r, start.r));
	const limit = pullKmS2 > 0 ? Math.sqrt((2 * COAST_DRIFT_BUDGET * crossedKm) / pullKmS2) : 0;
	const coastSeconds = isFinite(limit) ? Math.min(Math.max(coastFraction, 0), 1) * limit : 0;

	const burnSeconds = coastSeconds > 0 ? seedFor(coastSeconds) : flatOutBurn;
	if (burnSeconds === null || !(burnSeconds > 0)) return null;

	const totalSeconds = burns * burnSeconds + coastSeconds;
	const end = to(departJd + totalSeconds / SEC_PER_DAY);
	if (!end) return null;

	const chord = normalize(sub(end.r, start.r));
	const peakSpeedKms = accelKmS2 * burnSeconds;
	// Rest-to-rest, so a flipping arc arrives carrying only what it set out with;
	// a flyby arrives carrying that plus everything the one burn built.
	const arrivalVelocity = flips ? start.v : add(start.v, scale(chord, peakSpeedKms));

	return {
		problem: {
			start,
			target: to,
			departJd,
			accelKmS2,
			coastSeconds,
			flips,
			mu,
			seedBurnSeconds: burnSeconds
		},
		arc: {
			burnSeconds,
			coastSeconds,
			totalSeconds,
			flips,
			thrustDir: chord,
			arrivalVelocity,
			peakSpeedKms
		}
	};
}

/**
 * Build the constant-thrust arc leaving at `departJd` under `accelMs2`.
 * Returns null when either end can't be placed, or the drive can't fly the
 * crossing at all — a metre per second squared won't catch an interstellar
 * comet, and won't beat the Sun either.
 */
export function buildConstantThrustRoute(
	departure: TravelBody,
	target: TravelBody,
	departJd: number,
	accelMs2: number,
	options: ConstantThrustOptions = {}
): Route | null {
	const { departureMode = 'surface', arrivalMode = 'capture', aero = 'none' } = options;

	const solved = solveConstantThrustArc(departure, target, departJd, accelMs2, options);
	if (!solved) return null;
	const { problem, arc } = solved;

	const tofDays = arc.totalSeconds / SEC_PER_DAY;
	const arriveJd = departJd + tofDays;
	const end = problem.target(arriveJd);
	if (!end) return null;

	// What the ship is doing relative to the destination when it gets there, which
	// the integration answers rather than the model asserting it.
	const vInfArrKms = norm(sub(arc.arrivalVelocity, end.v));
	if (!isFinite(vInfArrKms)) return null;

	// Both wells are cleared at zero excess speed: the crossing does not start
	// until the ship is out of one and is over once it is falling into the other.
	// A held drive climbs out under thrust rather than on an asymptote, so the
	// plane it flies is the site's own — nothing further constrains it.
	const dep = departureCost(
		departure,
		0,
		departureMode,
		options.departureOrbit,
		surfaceSite(departure, options.departureSiteLatDeg, null)
	);
	const arr = arrivalCost(
		target,
		vInfArrKms,
		arrivalMode,
		aero,
		options.targetOrbit,
		surfaceSite(target, options.targetSiteLatDeg, null)
	);

	const burnDays = arc.burnSeconds / SEC_PER_DAY;
	// What one burn costs: the acceleration times the time it is held, whatever
	// gravity did to the speed that bought.
	const burnDvKms = problem.accelKmS2 * arc.burnSeconds;
	const legs: RouteLeg[] = [];
	if (dep.ascentKms > 0) legs.push({ kind: 'ascent', dvKms: dep.ascentKms, days: 0 });
	legs.push({ kind: 'injection', dvKms: dep.injectionKms, days: 0 });
	legs.push({ kind: 'boost', dvKms: burnDvKms, days: burnDays });
	if (arc.coastSeconds > 0) {
		legs.push({ kind: 'cruise', dvKms: 0, days: arc.coastSeconds / SEC_PER_DAY });
	}
	if (arc.flips) legs.push({ kind: 'brake', dvKms: burnDvKms, days: burnDays });
	legs.push(...arrivalLegs(arr, arrivalMode));

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
		departureOrbit: options.departureOrbit,
		targetOrbit: options.targetOrbit,
		aero,
		entrySpeedKms: arr.entrySpeedKms,
		constantThrust: accelMs2,
		peakSpeedKms: arc.peakSpeedKms,
		// Recorded as it was applied, not as it was asked for, so that two routes
		// built from requests the clamp made identical are identical.
		coastFraction: Math.min(Math.max(options.coastFraction ?? 0, 0), 1),
		thrustDir: arc.thrustDir
	};
}
