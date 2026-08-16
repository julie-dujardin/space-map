/**
 * Transfers that stay inside one system — Earth to its Moon, a planet to one of
 * its satellites.
 *
 * The interplanetary solver cannot answer these. It connects two orbits about a
 * distant primary, and here one end *is* the primary: there is no heliocentric
 * arc between them, and no hyperbolic escape at the departure, because you never
 * leave. What there is instead is an ellipse with its periapsis at the parking
 * orbit and its far end out at the satellite's distance — the lunar-transfer
 * geometry.
 *
 * The departure point around the primary is free, since you choose when in the
 * parking orbit to burn. That is what makes the arc solvable from a time of
 * flight alone: one ellipse in the family reaches the satellite's distance in
 * exactly that time, and the family runs from the Hohmann half-ellipse (slowest,
 * cheapest) up to a nearly parabolic arc (fastest).
 *
 * Coplanar throughout. The plane change between a parking orbit and the
 * satellite's orbit is a launch-azimuth question, and pricing it needs a launch
 * site rather than a body.
 */

import type { TravelBody } from './body';
import { SEC_PER_DAY } from './constants';
import { parkingRadiusKm } from './maneuvers';
import { elementsToState, type StateVector } from './state';
import { norm, sub } from './vec3';

/** One arc of the family, described where it matters: at each end. */
export interface RadialArc {
	/** Speed at the parking-orbit end, km/s. */
	vNearKms: number;
	/** Speed components at the satellite's distance, km/s. Radial is positive
	 *  outbound; the pair is what the satellite's own motion is differenced
	 *  against. */
	vFarRadialKms: number;
	vFarTangentialKms: number;
	/** Reciprocal semi-major axis, 1/km — energy, and the family's parameter.
	 *  Negative of it times μ is the arc's C3. */
	inverseAKm: number;
}

/**
 * How long the arc of energy `inverseA` takes from periapsis at `rNear` out to
 * `rFar`, in days. Null when that arc never reaches `rFar`.
 */
function arcDays(mu: number, rNear: number, rFar: number, inverseA: number): number | null {
	const a = 1 / inverseA;
	const e = 1 - rNear * inverseA;
	if (!(e >= 0) || e >= 1) return null;
	// r = a(1 − e·cos E) inverted at the far end; outside [−1, 1] the apoapsis
	// falls short of it. The slack is for the Hohmann arc itself, which lands
	// exactly on −1 and can round past it.
	const cosE = (1 - rFar * inverseA) / e;
	if (!(cosE >= -1 - 1e-9 && cosE <= 1 + 1e-9)) return null;
	const eccAnomaly = Math.acos(Math.min(1, Math.max(-1, cosE)));
	const meanAnomaly = eccAnomaly - e * Math.sin(eccAnomaly);
	return (meanAnomaly * Math.sqrt(a ** 3 / mu)) / SEC_PER_DAY;
}

/** Energy of the half-ellipse tangent to both radii — the family's slow end. */
function hohmannInverseA(rNearKm: number, rFarKm: number): number {
	return 2 / (rNearKm + rFarKm);
}

/**
 * The slowest and cheapest arc: the half-ellipse tangent to both radii, in days.
 * Every other arc in the family is faster and costs more.
 *
 * Read through `arcDays` rather than from the closed form, so that a grid built
 * to end here asks for a time this family can still answer: near half a turn the
 * arc-cosine loses enough precision that the two disagree by more than the
 * bracket's own slack.
 */
export function hohmannArcDays(mu: number, rNearKm: number, rFarKm: number): number {
	const inverseA = hohmannInverseA(rNearKm, rFarKm);
	const days = arcDays(mu, rNearKm, rFarKm, inverseA);
	return days ?? (Math.PI * Math.sqrt((1 / inverseA) ** 3 / mu)) / SEC_PER_DAY;
}

/**
 * The fastest arc worth offering, in days.
 *
 * The family's limit is parabolic — infinite semi-major axis, and a departure
 * burn that leaves the system rather than crossing it. This stops short of that,
 * far enough out that the remaining arcs all cost more than anyone would pay.
 */
const FASTEST_A_MULTIPLE = 60;

export function fastestArcDays(mu: number, rNearKm: number, rFarKm: number): number {
	return arcDays(mu, rNearKm, rFarKm, 1 / (FASTEST_A_MULTIPLE * (rNearKm + rFarKm))) ?? 0;
}

/** Bisection steps. Time of flight is smooth in energy, so this converges far
 *  tighter than the grid that asks for it. */
const SOLVE_STEPS = 60;

/**
 * The arc from a parking orbit at `rNearKm` out to `rFarKm` that takes
 * `tofDays`, or null when no arc in the family does.
 *
 * Slower than the Hohmann time is unreachable here by construction: that arc is
 * already the slowest that touches both radii, and anything longer would have to
 * arrive after apoapsis, on its way back down.
 */
export function solveRadialArc(
	mu: number,
	rNearKm: number,
	rFarKm: number,
	tofDays: number
): RadialArc | null {
	if (!(mu > 0) || !(rNearKm > 0) || !(rFarKm > rNearKm) || !(tofDays > 0)) return null;

	// Time of flight rises with energy, so the bracket runs from the fastest arc
	// to the Hohmann one.
	let lo = 1 / (FASTEST_A_MULTIPLE * (rNearKm + rFarKm));
	let hi = hohmannInverseA(rNearKm, rFarKm);
	const slowest = arcDays(mu, rNearKm, rFarKm, hi);
	const fastest = arcDays(mu, rNearKm, rFarKm, lo);
	if (slowest === null || fastest === null) return null;
	// The ends of the family are asked for by name — a grid runs to the Hohmann
	// time exactly — so the bracket has to admit its own edges.
	const slack = 1 + 1e-9;
	if (tofDays > slowest * slack || tofDays * slack < fastest) return null;

	for (let step = 0; step < SOLVE_STEPS; step++) {
		const mid = (lo + hi) / 2;
		const days = arcDays(mu, rNearKm, rFarKm, mid);
		if (days === null) {
			// Only reachable through rounding at the bracket's edge.
			lo = mid;
			continue;
		}
		if (days < tofDays) lo = mid;
		else hi = mid;
	}

	const inverseA = (lo + hi) / 2;
	const e = 1 - rNearKm * inverseA;
	const semiLatus = (1 - e * e) / inverseA;
	const vNear = Math.sqrt(mu * (2 / rNearKm - inverseA));
	const vFar = Math.sqrt(mu * (2 / rFarKm - inverseA));
	const vFarTangential = Math.sqrt(mu * semiLatus) / rFarKm;
	// Rounding can leave the tangential part a hair over the total.
	const vFarRadial = Math.sqrt(Math.max(0, vFar * vFar - vFarTangential * vFarTangential));

	if (!isFinite(vNear) || !isFinite(vFarTangential) || !isFinite(vFarRadial)) return null;
	return {
		vNearKms: vNear,
		vFarRadialKms: vFarRadial,
		vFarTangentialKms: vFarTangential,
		inverseAKm: inverseA
	};
}

/**
 * Whether the primary's elements describe it going round the barycentre they
 * share, rather than something else.
 *
 * Two bodies about a common barycentre keep step: one period, opposite sides.
 * An element set that says otherwise is not describing that motion — a planet's
 * row can hold a degenerate fit, since its position comes from sampled ephemeris
 * and the elements are only carried alongside — and differencing it would move
 * the primary by thousands of km an hour.
 */
function orbitsInLockstep(primary: TravelBody, satellite: TravelBody): boolean {
	const ratio = primary.elements.n / satellite.elements.n;
	return primary.elements.e < 1 && ratio > 0.5 && ratio < 2;
}

/** Pairs already reported. A grid asks this thousands of times for the same two
 *  bodies, and the answer never changes — saying it once keeps a solve off the
 *  console, where every line costs real time with a debugger attached. */
const reportedPairs = new Set<string>();

function reportNoCompanionOrbit(primary: TravelBody, satellite: TravelBody): void {
	const key = `${primary.id}>${satellite.id}`;
	if (reportedPairs.has(key)) return;
	reportedPairs.add(key);
	console.debug(
		`[travel] ${primary.id} has no companion orbit to ${satellite.id} ` +
			`(e=${primary.elements.e}, n=${primary.elements.n} against ${satellite.elements.n}) ` +
			`— placing it at the barycentre.`
	);
}

/** Whether this pair's gap is measured rather than propagated. Where it is, the
 *  measurement is the only answer — see {@link sampledState}. */
function isMeasured(satellite: TravelBody, primary: TravelBody): boolean {
	const samples = satellite.samples;
	return samples !== undefined && samples.centerId === primary.id && samples.jds.length > 1;
}

/**
 * The satellite where it was measured, or null outside the dates that were.
 *
 * Null rather than a fallback: a body carrying these is one whose conic is a
 * fiction, so past the last sample there is no answer to give and a search
 * simply stops offering trips it cannot describe. Reaching for the elements
 * there is how the far end ends up half a million km from the body.
 *
 * Cubic Hermite, so the sampled velocities shape the curve between dates rather
 * than only being read at them; a chord across a two-day gap would sag by a
 * hundred kilometres, which is nothing here, but the plane and the satellite's
 * own motion are read off this too and those want the tangent right.
 */
function sampledState(satellite: TravelBody, primary: TravelBody, jd: number): StateVector | null {
	const samples = satellite.samples;
	if (!samples) return null;
	const { jds, r, v } = samples;
	const last = jds.length - 1;
	if (jd < jds[0] || jd > jds[last]) return null;

	let lo = 0;
	let hi = last;
	while (hi - lo > 1) {
		const mid = (lo + hi) >> 1;
		if (jds[mid] <= jd) lo = mid;
		else hi = mid;
	}
	const span = jds[hi] - jds[lo];
	if (!(span > 0)) return { r: r[lo], v: v[lo], mu: primary.mu };

	// Hermite on the interval, with the velocities scaled into its own parameter.
	const t = (jd - jds[lo]) / span;
	const secs = span * SEC_PER_DAY;
	const h00 = 2 * t ** 3 - 3 * t ** 2 + 1;
	const h10 = t ** 3 - 2 * t ** 2 + t;
	const h01 = -2 * t ** 3 + 3 * t ** 2;
	const h11 = t ** 3 - t ** 2;
	const at = (i: number): number =>
		h00 * r[lo][i] + h10 * secs * v[lo][i] + h01 * r[hi][i] + h11 * secs * v[hi][i];
	return {
		r: [at(0), at(1), at(2)],
		v: [
			v[lo][0] + (v[hi][0] - v[lo][0]) * t,
			v[lo][1] + (v[hi][1] - v[lo][1]) * t,
			v[lo][2] + (v[hi][2] - v[lo][2]) * t
		],
		mu: primary.mu
	};
}

/**
 * The satellite's position and velocity relative to its primary.
 *
 * Measured positions answer on their own where they exist: nothing below can
 * describe a body that is not on a conic about its primary at all, so past the
 * dates that were measured the answer is that there is none.
 *
 * Elements about a shared barycentre describe how each end moves about *it*, so
 * the separation is the difference between the two — which matters for the Moon,
 * whose barycentre sits 4,600 km from Earth's centre, most of the way out to a
 * parking orbit. Where the primary's own orbit is unusable or absent — the
 * giants, whose barycentre is inside them — it sits at the centre instead, which
 * costs at most that offset.
 */
export function relativeState(
	satellite: TravelBody,
	primary: TravelBody,
	jd: number
): StateVector | null {
	if (isMeasured(satellite, primary)) return sampledState(satellite, primary, jd);
	const s = elementsToState(satellite.elements, jd);
	if (!s) return null;
	if (satellite.parentId !== primary.parentId) return s;
	if (!orbitsInLockstep(primary, satellite)) {
		reportNoCompanionOrbit(primary, satellite);
		return s;
	}
	const p = elementsToState(primary.elements, jd);
	return p ? { r: sub(s.r, p.r), v: sub(s.v, p.v), mu: s.mu } : s;
}

/** How far apart they are at `jd`, km. */
export function separationKm(
	satellite: TravelBody,
	primary: TravelBody,
	jd: number
): number | null {
	const state = relativeState(satellite, primary, jd);
	return state ? norm(state.r) : null;
}

/** Slowest and fastest crossing of the gap, days — the whole family's span. */
export interface SystemArcBounds {
	slowestDays: number;
	fastestDays: number;
}

/** Separation samples across a window. Enough to catch an eccentric satellite's
 *  nearest and furthest without the cost mattering. */
const BOUNDS_SAMPLES = 13;

/**
 * How long a crossing can take, over a window of dates.
 *
 * The gap is not fixed — the Moon swings between 356,000 and 407,000 km — so the
 * family's own limits move with it, and a grid built from one date's limits
 * would ask for arcs that do not exist on another. Sampling the window and
 * taking the widest bounds leaves the grid covering every arc that solves
 * anywhere in it, and empty where one does not.
 */
export function systemArcBounds(
	primary: TravelBody,
	satellite: TravelBody,
	fromJd: number,
	toJd: number = fromJd
): SystemArcBounds | null {
	const rNear = parkingRadiusKm(primary);
	if (!(primary.mu > 0)) return null;

	let slowestDays = -Infinity;
	let fastestDays = Infinity;
	const step = (toJd - fromJd) / Math.max(1, BOUNDS_SAMPLES - 1);
	for (let i = 0; i < (toJd > fromJd ? BOUNDS_SAMPLES : 1); i++) {
		const rFar = separationKm(satellite, primary, fromJd + i * step);
		if (rFar === null || !(rFar > rNear)) continue;
		slowestDays = Math.max(slowestDays, hohmannArcDays(primary.mu, rNear, rFar));
		fastestDays = Math.min(fastestDays, fastestArcDays(primary.mu, rNear, rFar));
	}
	if (!isFinite(slowestDays) || !isFinite(fastestDays)) return null;
	return { slowestDays, fastestDays };
}
