/**
 * When the next transfer opportunity is. The classic answer is the synodic
 * period, which assumes circular coplanar orbits. Since the app already
 * propagates real positions, this evaluates the actual geometry instead and
 * only borrows the ideal phase angle from Hohmann — so an eccentric target
 * like Mars gets windows that drift and vary in cost the way real ones do.
 */

import { AU_KM } from '$lib/math/units';
import type { TravelBody } from './body';
import { GM_SUN_KM3_S2, SEC_PER_DAY } from './constants';
import { elementsToState } from './state';
import { dot } from './vec3';

const TWO_PI = Math.PI * 2;

/**
 * Days between successive identical alignments of two bodies. Infinite when the
 * orbits have the same period, and null when either mean motion is unusable.
 */
export function synodicPeriodDays(a: TravelBody, b: TravelBody): number | null {
	const nA = a.elements.n;
	const nB = b.elements.n;
	if (!isFinite(nA) || !isFinite(nB) || nA <= 0 || nB <= 0) return null;
	const diff = Math.abs(nA - nB);
	if (diff === 0) return Infinity;
	return 360 / diff;
}

/** Time of flight on the idealized Hohmann transfer between two orbits, days. */
export function hohmannTransferDays(
	a: TravelBody,
	b: TravelBody,
	mu = GM_SUN_KM3_S2
): number | null {
	const rA = a.elements.a * AU_KM;
	const rB = b.elements.a * AU_KM;
	if (!(rA > 0) || !(rB > 0)) return null;
	return halfEllipseDays((rA + rB) / 2, mu);
}

/**
 * Time to cross between where the two bodies are *now*, days. Stands in for
 * the Hohmann time when semi-major axes can't supply one — an escaping probe
 * has none, an eccentric orbit's is nowhere near where the body is. Half an
 * ellipse spanning the two current distances is not a transfer anyone would
 * fly, but is the right order of magnitude for the search bounds.
 */
export function crossingTimeDays(
	a: TravelBody,
	b: TravelBody,
	jd: number,
	mu = GM_SUN_KM3_S2
): number | null {
	const sA = elementsToState(a.elements, jd, mu);
	const sB = elementsToState(b.elements, jd, mu);
	if (!sA || !sB) return null;
	const aT = (radius(sA.r) + radius(sB.r)) / 2;
	if (!(aT > 0)) return null;
	return halfEllipseDays(aT, mu);
}

/**
 * How far a body's distance may sit from its semi-major axis before the axis
 * stops standing in for it.
 */
const AXIS_TOLERANCE = 0.25;
/**
 * The share of its own distance a target may cover while the crossing is under
 * way before it counts as leaving rather than waiting.
 */
const CHASE_TRAVEL_FRACTION = 0.5;

export interface TransferScale {
	/** How long a crossing between the two bodies takes, days. */
	days: number;
	/**
	 * True when the target moves an appreciable part of its own distance during
	 * that crossing, so no departure date is a window and the arcs worth flying
	 * are the fast ones.
	 */
	chase: boolean;
}

/**
 * The timescale a transfer between two bodies is measured against, and
 * whether the target must be chased rather than met. Hohmann time reads a
 * body's distance off its semi-major axis, which only holds while the orbit
 * is round: C/2021 P2 has a = 2474 AU but sits at 10 AU, so scaling off the
 * axis would grid against a 21,000-year half-orbit and return nothing but
 * geological-age routes. Where axis and distance disagree, distance wins, and
 * a target crossing much of that distance meanwhile is one to chase. Returns
 * null when either body's orbit won't yield a position.
 */
export function transferScale(
	a: TravelBody,
	b: TravelBody,
	jd: number,
	mu = GM_SUN_KM3_S2
): TransferScale | null {
	const sA = elementsToState(a.elements, jd, mu);
	const sB = elementsToState(b.elements, jd, mu);
	if (!sA || !sB) return null;
	const rA = radius(sA.r);
	const rB = radius(sB.r);
	if (!(rA > 0) || !(rB > 0)) return null;

	const ideal = hohmannTransferDays(a, b, mu);
	const round = describesDistance(a, rA) && describesDistance(b, rB);
	const days = ideal !== null && round ? ideal : halfEllipseDays((rA + rB) / 2, mu);
	if (!(days > 0)) return null;

	// How fast the gap the arc has to close is opening or closing, km/s.
	const radialKms = Math.abs(dot(sB.r, sB.v)) / rB;
	return {
		days,
		chase: ideal === null || radialKms * days * SEC_PER_DAY > CHASE_TRAVEL_FRACTION * rB
	};
}

/** True when a body's semi-major axis stands in for where it actually is. */
function describesDistance(body: TravelBody, rKm: number): boolean {
	const axisKm = body.elements.a * AU_KM;
	return axisKm > 0 && Math.abs(axisKm - rKm) <= AXIS_TOLERANCE * axisKm;
}

function halfEllipseDays(aKm: number, mu: number): number {
	return (Math.PI * Math.sqrt(aKm ** 3 / mu)) / SEC_PER_DAY;
}

function radius(r: readonly [number, number, number]): number {
	return Math.hypot(r[0], r[1], r[2]);
}

/**
 * Phase angle the target must lead the departure body by at launch, radians in
 * (−π, π]. Negative means the target trails.
 */
export function requiredPhaseAngle(
	a: TravelBody,
	b: TravelBody,
	mu = GM_SUN_KM3_S2
): number | null {
	const tof = hohmannTransferDays(a, b, mu);
	if (tof === null) return null;
	const nB = (b.elements.n * Math.PI) / 180; // rad/day
	return wrapPi(Math.PI - nB * tof);
}

/** Heliocentric ecliptic longitude of a body at `jd`, radians. */
function longitude(body: TravelBody, jd: number, mu: number): number | null {
	const s = elementsToState(body.elements, jd, mu);
	if (!s) return null;
	return Math.atan2(s.r[1], s.r[0]);
}

function wrapPi(angle: number): number {
	let x = angle % TWO_PI;
	if (x > Math.PI) x -= TWO_PI;
	if (x <= -Math.PI) x += TWO_PI;
	return x;
}

/**
 * The next `count` departure dates where the two bodies reach the Hohmann
 * phase angle, searching forward from `fromJd`. These are window centres, not
 * edges — a porkchop around one gives the usable spread. Returns fewer than
 * `count` if the search horizon runs out, and none for a chased target: a
 * comet on its way out is somewhere else every year, so an alignment it'll
 * never repeat isn't a date to wait for.
 */
export function nextTransferWindows(
	a: TravelBody,
	b: TravelBody,
	fromJd: number,
	count = 3,
	mu = GM_SUN_KM3_S2
): number[] {
	const scale = transferScale(a, b, fromJd, mu);
	if (!scale || scale.chase) return [];
	const phase = requiredPhaseAngle(a, b, mu);
	const synodic = synodicPeriodDays(a, b);
	if (phase === null || synodic === null || !isFinite(synodic)) return [];

	// A synodic period contains exactly one alignment, so sampling it finely
	// enough to catch one sign change per period is sufficient.
	const step = synodic / 180;
	const horizon = fromJd + synodic * (count + 1.2);

	const offset = (jd: number): number | null => {
		const lonA = longitude(a, jd, mu);
		const lonB = longitude(b, jd, mu);
		if (lonA === null || lonB === null) return null;
		return wrapPi(lonB - lonA - phase);
	};

	const windows: number[] = [];
	let prevJd = fromJd;
	let prev = offset(prevJd);
	for (let jd = fromJd + step; jd <= horizon && windows.length < count; jd += step) {
		const curr = offset(jd);
		if (prev === null || curr === null) {
			prevJd = jd;
			prev = curr;
			continue;
		}
		// A jump of more than π is the angle wrapping, not a crossing.
		if (prev <= 0 !== curr <= 0 && Math.abs(curr - prev) < Math.PI) {
			windows.push(bisect(offset, prevJd, jd));
		}
		prevJd = jd;
		prev = curr;
	}
	return windows;
}

function bisect(f: (jd: number) => number | null, lo: number, hi: number): number {
	let a = lo;
	let b = hi;
	const fa = f(a);
	if (fa === null) return (a + b) / 2;
	const signA = fa <= 0;
	for (let i = 0; i < 40; i++) {
		const mid = (a + b) / 2;
		const fm = f(mid);
		if (fm === null) break;
		if (fm <= 0 === signA) a = mid;
		else b = mid;
	}
	return (a + b) / 2;
}
