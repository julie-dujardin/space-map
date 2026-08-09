/**
 * Routes that go the long way round on purpose: out to a third body, past it,
 * and on to the destination.
 *
 * The trajectory is two Lambert arcs sharing an endpoint, patched by a swing-by
 * that has to turn the first arc's excess velocity into the second's. Anything
 * it cannot turn or match is paid as a burn at closest approach, so a sequence
 * that does not really work simply prices badly rather than being ruled out —
 * the search then ignores it, which is the same answer arrived at cheaply.
 *
 * The search is a coarse sweep over three dates followed by a local shrink, the
 * same shape as the direct porkchop's refinement but one dimension larger. What
 * makes it tractable is where the departures are sampled: a useful geometry is
 * weeks wide and the next one is years away, so a grid laid evenly across a
 * decade would step straight over every one of them. Instead the departures are
 * seeded on the *first* leg's transfer windows, which `windows` already finds;
 * whether the third body is also in the right place is what then separates one
 * seed from another.
 *
 * One swing-by only. Two is a different problem — the useful basins are narrow
 * and far apart, so it wants a global optimiser rather than a grid — and it is
 * also where the launch-energy saving lives: the Venus-Venus-Earth run that got
 * Cassini to Jupiter cheaply is out of reach here, so a single pass buys the
 * arrival and not the departure.
 */

import { AU_KM } from '$lib/math/units';
import type { TravelBody } from './body';
import { sphereOfInfluenceKm } from './body';
import { GM_SUN_KM3_S2, SEC_PER_DAY } from './constants';
import { solveFlyby, type FlybyPass } from './flyby';
import { solveLambert } from './lambert';
import { arrivalCost, characteristicEnergy, departureCost } from './maneuvers';
import type { Route, RouteLeg, RouteOptions } from './route';
import { elementsToState } from './state';
import { norm, sub } from './vec3';
import { hohmannTransferDays, nextTransferWindows } from './windows';

/**
 * Build the two-arc route leaving at `departJd`, passing `via` after `tof1Days`
 * and arriving `tof2Days` after that.
 *
 * Returns null when either arc has no solution or the swing-by cannot be flown
 * at all — the pass would have to go through the body.
 */
export function buildAssistRoute(
	departure: TravelBody,
	via: TravelBody,
	target: TravelBody,
	departJd: number,
	tof1Days: number,
	tof2Days: number,
	options: RouteOptions = {}
): Route | null {
	const {
		departureMode = 'surface',
		arrivalMode = 'capture',
		centralMu = GM_SUN_KM3_S2,
		retrograde = false
	} = options;
	if (!(tof1Days > 0) || !(tof2Days > 0)) return null;

	const flybyJd = departJd + tof1Days;
	const arriveJd = flybyJd + tof2Days;

	const from = elementsToState(departure.elements, departJd, centralMu);
	const mid = elementsToState(via.elements, flybyJd, centralMu);
	const to = elementsToState(target.elements, arriveJd, centralMu);
	if (!from || !mid || !to) return null;

	const arc1 = solveLambert(from.r, mid.r, tof1Days * SEC_PER_DAY, centralMu, retrograde);
	if (!arc1) return null;
	const arc2 = solveLambert(mid.r, to.r, tof2Days * SEC_PER_DAY, centralMu, retrograde);
	if (!arc2) return null;

	const vInfDep = norm(sub(arc1.v1, from.v));
	const vInfIn = sub(arc1.v2, mid.v);
	const vInfOut = sub(arc2.v1, mid.v);
	const vInfArr = norm(sub(arc2.v2, to.v));
	if (!isFinite(vInfDep) || !isFinite(vInfArr)) return null;

	// Past the sphere of influence the pass is not a swing-by at all, so that is
	// where a periapsis the geometry pushes outward stops being credited.
	const soi = sphereOfInfluenceKm(via, centralMu, via.elements.a * AU_KM);
	const pass = solveFlyby(via, vInfIn, vInfOut, soi);
	if (!pass) return null;

	const dep = departureCost(departure, vInfDep, departureMode);
	const arr = arrivalCost(target, vInfArr, arrivalMode);

	const legs: RouteLeg[] = [];
	if (dep.ascentKms > 0) legs.push({ kind: 'ascent', dvKms: dep.ascentKms, days: 0 });
	legs.push({ kind: 'injection', dvKms: dep.injectionKms, days: 0 });
	legs.push({ kind: 'cruise', dvKms: 0, days: tof1Days });
	legs.push({ kind: 'assist', dvKms: pass.dvKms, days: 0 });
	legs.push({ kind: 'cruise', dvKms: 0, days: tof2Days });
	if (arrivalMode !== 'flyby') {
		legs.push({ kind: 'capture', dvKms: arr.captureKms, days: 0, aerobraked: arr.aerobraked });
	}
	if (arr.descentKms > 0) {
		legs.push({ kind: 'descent', dvKms: arr.descentKms, days: 0, aerobraked: arr.aerobraked });
	}

	const totalDvKms = legs.reduce((sum, leg) => sum + leg.dvKms, 0);
	if (!isFinite(totalDvKms)) return null;

	const flyby: FlybyPass = {
		bodyId: via.id,
		jd: flybyJd,
		altitudeKm: pass.periapsisKm - via.radiusKm,
		dvKms: pass.dvKms,
		turnDeg: (pass.turnRad * 180) / Math.PI,
		vInfInKms: norm(vInfIn),
		vInfOutKms: norm(vInfOut)
	};

	return {
		departureId: departure.id,
		targetId: target.id,
		departJd,
		arriveJd,
		tofDays: tof1Days + tof2Days,
		legs,
		totalDvKms,
		inSpaceDvKms: totalDvKms - dep.ascentKms,
		c3Km2S2: characteristicEnergy(vInfDep),
		vInfDepKms: vInfDep,
		vInfArrKms: vInfArr,
		departureMode,
		arrivalMode,
		flybys: [flyby]
	};
}

export interface AssistSearchOptions extends RouteOptions {
	departFromJd: number;
	departToJd: number;
	/** Bounds on each cruise, days. */
	tof1MinDays: number;
	tof1MaxDays: number;
	tof2MinDays: number;
	tof2MaxDays: number;
	departSteps?: number;
	tof1Steps?: number;
	tof2Steps?: number;
}

const DEFAULT_DEPART_STEPS = 48;
const DEFAULT_TOF_STEPS = 22;

/**
 * The cheapest route through `via` in the given window, or null when none of the
 * grid solves.
 *
 * The sweep is ordered so the first arc is solved once per departure/first-leg
 * pair rather than once per cell; the inner loop over the second leg is then a
 * single Lambert solve and a swing-by each.
 */
export function searchAssist(
	departure: TravelBody,
	via: TravelBody,
	target: TravelBody,
	options: AssistSearchOptions
): Route | null {
	const {
		departFromJd,
		departToJd,
		tof1MinDays,
		tof1MaxDays,
		tof2MinDays,
		tof2MaxDays,
		departSteps = DEFAULT_DEPART_STEPS,
		tof1Steps = DEFAULT_TOF_STEPS,
		tof2Steps = DEFAULT_TOF_STEPS,
		...routeOptions
	} = options;

	let best: Route | null = null;
	const departStep = departSteps > 1 ? (departToJd - departFromJd) / (departSteps - 1) : 0;
	const tof1Step = tof1Steps > 1 ? (tof1MaxDays - tof1MinDays) / (tof1Steps - 1) : 0;
	const tof2Step = tof2Steps > 1 ? (tof2MaxDays - tof2MinDays) / (tof2Steps - 1) : 0;

	for (let i = 0; i < departSteps; i++) {
		const departJd = departFromJd + i * departStep;
		for (let j = 0; j < tof1Steps; j++) {
			const tof1 = tof1MinDays + j * tof1Step;
			for (let k = 0; k < tof2Steps; k++) {
				const tof2 = tof2MinDays + k * tof2Step;
				const route = buildAssistRoute(departure, via, target, departJd, tof1, tof2, routeOptions);
				if (route && (!best || route.totalDvKms < best.totalDvKms)) best = route;
			}
		}
	}
	if (!best) return null;

	return refine(departure, via, target, best, {
		departSpan: departStep,
		tof1Span: tof1Step,
		tof2Span: tof2Step,
		bounds: options,
		routeOptions
	});
}

interface RefineContext {
	departSpan: number;
	tof1Span: number;
	tof2Span: number;
	bounds: AssistSearchOptions;
	routeOptions: RouteOptions;
}

/**
 * Shrink a local search around the grid's best cell.
 *
 * Same idea as the direct porkchop's refinement, in three dimensions instead of
 * two: a cell wide enough to sweep is far wider than the basin around a real
 * window, so the raw grid minimum can sit a kilometre per second above the true
 * one. Neighbours are tried one axis at a time rather than as a full 26-point
 * cube — the extra passes cost less than the extra points.
 */
function refine(
	departure: TravelBody,
	via: TravelBody,
	target: TravelBody,
	seed: Route,
	ctx: RefineContext
): Route {
	const { bounds, routeOptions } = ctx;
	let best = seed;
	let departSpan = ctx.departSpan;
	let tof1Span = ctx.tof1Span;
	let tof2Span = ctx.tof2Span;

	for (let pass = 0; pass < 8; pass++) {
		departSpan /= 2;
		tof1Span /= 2;
		tof2Span /= 2;
		const tof1 = best.flybys![0].jd - best.departJd;
		const tof2 = best.tofDays - tof1;
		for (const dDepart of [-departSpan, 0, departSpan]) {
			for (const d1 of [-tof1Span, 0, tof1Span]) {
				for (const d2 of [-tof2Span, 0, tof2Span]) {
					if (dDepart === 0 && d1 === 0 && d2 === 0) continue;
					const route = buildAssistRoute(
						departure,
						via,
						target,
						clamp(best.departJd + dDepart, bounds.departFromJd, bounds.departToJd),
						clamp(tof1 + d1, bounds.tof1MinDays, bounds.tof1MaxDays),
						clamp(tof2 + d2, bounds.tof2MinDays, bounds.tof2MaxDays),
						routeOptions
					);
					if (route && route.totalDvKms < best.totalDvKms) best = route;
				}
			}
		}
	}
	return best;
}

function clamp(value: number, min: number, max: number): number {
	return value < min ? min : value > max ? max : value;
}

/**
 * How far ahead to look for a swing-by, days.
 *
 * Far further than the direct search, and necessarily so: the alignment that
 * makes an assist worth flying comes round on the two synodic periods at once,
 * and inside one of them there may be none. Twenty years covers eighteen
 * Earth-Jupiter windows, which is enough to find a good one for every pair the
 * planner offers.
 */
const HORIZON_DAYS = 20 * 365.25;

/** Departure dates to try either side of a window's centre, and how many. */
const SEED_SLACK_DAYS = 120;
const SEED_DEPART_STEPS = 11;

/** Each cruise as a multiple of its own Hohmann time. The second leg reaches far
 *  lower than the first: after a strong pass the craft is not on a transfer
 *  orbit any more, and the arc that follows is much faster than Hohmann. */
const TOF1_FACTORS = [0.4, 1.6];
const TOF2_FACTORS = [0.12, 1.4];

export interface AssistOptions extends RouteOptions {
	/** Now, on the app's clock — no departure before it is considered. */
	nowJd: number;
	/** How far ahead to look for a window, days. */
	horizonDays?: number;
}

/**
 * The cheapest single-swing-by route to `target`, over every candidate in
 * `vias`, or null when none of them yields one.
 *
 * Costs a few hundred milliseconds per candidate, so this belongs off the main
 * thread and behind the direct answer rather than in front of it.
 *
 * Candidates that are one of the trip's own ends are skipped: leaving a body to
 * swing past it again is a real manoeuvre, but it needs a burn out in deep space
 * to set up, and this model has nowhere to put one.
 */
export function findAssistRoute(
	departure: TravelBody,
	target: TravelBody,
	vias: readonly TravelBody[],
	options: AssistOptions
): Route | null {
	const { nowJd, horizonDays = HORIZON_DAYS, ...routeOptions } = options;
	let best: Route | null = null;

	for (const via of vias) {
		if (via.id === departure.id || via.id === target.id) continue;
		const route = bestThrough(departure, via, target, nowJd, horizonDays, routeOptions);
		if (route && (!best || route.totalDvKms < best.totalDvKms)) best = route;
	}
	return best;
}

function bestThrough(
	departure: TravelBody,
	via: TravelBody,
	target: TravelBody,
	nowJd: number,
	horizonDays: number,
	routeOptions: RouteOptions
): Route | null {
	const mu = routeOptions.centralMu ?? GM_SUN_KM3_S2;
	const hop1 = hohmannTransferDays(departure, via, mu);
	const hop2 = hohmannTransferDays(via, target, mu);
	// Both legs are scaled against a Hohmann time. A body with no semi-major axis
	// to take one from — an escaping probe — cannot be one of the three.
	if (hop1 === null || hop2 === null || !(hop1 > 0) || !(hop2 > 0)) return null;

	const seeds = nextTransferWindows(departure, via, nowJd, MAX_SEEDS, mu).filter(
		(jd) => jd < nowJd + horizonDays
	);

	let best: Route | null = null;
	for (const seed of seeds) {
		const route = searchAssist(departure, via, target, {
			...routeOptions,
			departFromJd: Math.max(nowJd, seed - SEED_SLACK_DAYS),
			departToJd: seed + SEED_SLACK_DAYS,
			tof1MinDays: hop1 * TOF1_FACTORS[0],
			tof1MaxDays: hop1 * TOF1_FACTORS[1],
			tof2MinDays: hop2 * TOF2_FACTORS[0],
			tof2MaxDays: hop2 * TOF2_FACTORS[1],
			departSteps: SEED_DEPART_STEPS
		});
		if (route && (!best || route.totalDvKms < best.totalDvKms)) best = route;
	}
	return best;
}

/** Enough to cover the horizon for the slowest pair worth seeding on. */
const MAX_SEEDS = 40;
