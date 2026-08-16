/**
 * Sweep departure date against time of flight to find what transfers exist.
 *
 * This is the porkchop plot's data, and also where the three offered routes
 * come from. Costs are full mission Δv rather than launch energy alone, so the
 * arrival mode genuinely changes which route wins — a flyby of an outer planet
 * favours a fast arc, an orbiter favours a slow one.
 */

import type { TravelBody } from './body';
import { arrivalCampaignDays } from './maneuvers';
import { buildRoute, type Route, type RouteOptions } from './route';

export interface PorkchopOptions extends RouteOptions, DeadlineOptions {
	/** Earliest departure to consider, JD. */
	departFromJd: number;
	/** Latest departure to consider, JD. */
	departToJd: number;
	/** Shortest and longest cruise to consider, days. */
	tofMinDays: number;
	tofMaxDays: number;
	departSteps?: number;
	tofSteps?: number;
}

export interface DeadlineOptions {
	/**
	 * The date the trip has to be over by, JD. Absent means no deadline. Over,
	 * not landed at: an aerobraking arrival is captured months before the
	 * campaign that follows has walked the orbit down, and the trip hasn't
	 * delivered until that's finished — every search below takes those months
	 * off the deadline before holding a crossing to it.
	 *
	 * Belongs to choosing a route, not pricing one, so it's not a
	 * `RouteOption`: every arc a search finds is real and priced the same way,
	 * and this only says which answer the question asked. The grid stays
	 * whole — it's the field the reader picks off, and blanking half of it
	 * would hide arcs that moving the date brings back.
	 */
	deadlineJd?: number;
}

export interface PorkchopGrid {
	departJds: Float64Array;
	tofDays: Float64Array;
	/** Row-major `[departIdx * tofSteps + tofIdx]`; NaN where no arc solves. */
	totalDvKms: Float32Array;
	c3Km2S2: Float32Array;
	vInfArrKms: Float32Array;
	departSteps: number;
	tofSteps: number;
	/** How many cells produced a usable transfer. */
	solvedCount: number;
}

const DEFAULT_DEPART_STEPS = 160;
const DEFAULT_TOF_STEPS = 160;

export function computePorkchop(
	departure: TravelBody,
	target: TravelBody,
	options: PorkchopOptions
): PorkchopGrid {
	const {
		departFromJd,
		departToJd,
		tofMinDays,
		tofMaxDays,
		departSteps = DEFAULT_DEPART_STEPS,
		tofSteps = DEFAULT_TOF_STEPS,
		...routeOptions
	} = options;

	const departJds = new Float64Array(departSteps);
	const tofDays = new Float64Array(tofSteps);
	const departStep = departSteps > 1 ? (departToJd - departFromJd) / (departSteps - 1) : 0;
	const tofStep = tofSteps > 1 ? (tofMaxDays - tofMinDays) / (tofSteps - 1) : 0;
	for (let i = 0; i < departSteps; i++) departJds[i] = departFromJd + i * departStep;
	for (let j = 0; j < tofSteps; j++) tofDays[j] = tofMinDays + j * tofStep;

	const cells = departSteps * tofSteps;
	const totalDvKms = new Float32Array(cells).fill(NaN);
	const c3Km2S2 = new Float32Array(cells).fill(NaN);
	const vInfArrKms = new Float32Array(cells).fill(NaN);

	let solvedCount = 0;
	for (let i = 0; i < departSteps; i++) {
		for (let j = 0; j < tofSteps; j++) {
			const route = buildRoute(departure, target, departJds[i], tofDays[j], routeOptions);
			if (!route) continue;
			const k = i * tofSteps + j;
			totalDvKms[k] = route.totalDvKms;
			c3Km2S2[k] = route.c3Km2S2;
			vInfArrKms[k] = route.vInfArrKms;
			solvedCount++;
		}
	}

	return {
		departJds,
		tofDays,
		totalDvKms,
		c3Km2S2,
		vInfArrKms,
		departSteps,
		tofSteps,
		solvedCount
	};
}

export type RouteProfile = 'fast' | 'balanced' | 'efficient';

export interface RouteChoice {
	profile: RouteProfile;
	route: Route;
}

interface Candidate {
	departJd: number;
	tofDays: number;
	dv: number;
	/** Days from the start of the search until arrival. */
	wait: number;
}

/**
 * Pick the three routes to offer. The time axis is *arrival* measured from
 * the start of the search, not cruise length, so waiting two years for a
 * cheap window counts against that route the way a traveller would count it.
 *
 * Candidates are first reduced to the Pareto front — no route offered when
 * another is both cheaper and sooner. `efficient` and `fast` are its ends;
 * `balanced` is the knee, closest to the unreachable corner where both
 * objectives are best.
 *
 * A deadline is applied here rather than to the result, which is the whole
 * difference between three routes and one: the cheapest arc is almost always
 * the latest one, so filtering afterwards deletes `efficient` and usually
 * `balanced` with nothing to replace them. Ruling those cells out first makes
 * the front the front of what can actually be flown.
 */
export function selectRoutes(
	grid: PorkchopGrid,
	departure: TravelBody,
	target: TravelBody,
	options: RouteOptions & DeadlineOptions = {}
): RouteChoice[] {
	const searchStartJd = grid.departJds[0];
	const latestArriveJd = latestArrival(target, options);
	const candidates: Candidate[] = [];
	for (let i = 0; i < grid.departSteps; i++) {
		for (let j = 0; j < grid.tofSteps; j++) {
			const dv = grid.totalDvKms[i * grid.tofSteps + j];
			if (!isFinite(dv)) continue;
			const departJd = grid.departJds[i];
			const tof = grid.tofDays[j];
			if (departJd + tof > latestArriveJd) continue;
			candidates.push({ departJd, tofDays: tof, dv, wait: departJd + tof - searchStartJd });
		}
	}
	if (candidates.length === 0) return [];

	const front = paretoFront(candidates);
	const efficient = front.reduce((a, b) => (b.dv < a.dv ? b : a));
	const fast = front.reduce((a, b) => (b.wait < a.wait ? b : a));
	const balanced = kneePoint(front);

	const picks: Array<[RouteProfile, Candidate]> = [
		['fast', fast],
		['balanced', balanced],
		['efficient', efficient]
	];

	const chosen: RouteChoice[] = [];
	const seen = new Set<string>();
	for (const [profile, candidate] of picks) {
		const refined = refine(departure, target, candidate, grid, options, latestArriveJd);
		if (!refined) continue;
		// Distinct profiles can land on the same cell when the front is short;
		// offering the same route three times would be noise.
		const key = `${refined.departJd.toFixed(3)}:${refined.tofDays.toFixed(3)}`;
		if (seen.has(key)) continue;
		seen.add(key);
		chosen.push({ profile, route: refined });
	}
	return chosen;
}

/**
 * The latest a crossing may end and still leave the trip finished in time,
 * JD, or Infinity when no deadline was set. Taken once for the whole search:
 * what a trip owes after arrival is a fact about how it ends, not which arc
 * got it there.
 */
function latestArrival(target: TravelBody, options: RouteOptions & DeadlineOptions): number {
	const { deadlineJd, arrivalMode = 'capture', aero = 'none', targetOrbit } = options;
	if (deadlineJd == null) return Infinity;
	return deadlineJd - arrivalCampaignDays(target, arrivalMode, aero, targetOrbit);
}

/** Candidates not dominated on both cost and arrival time. */
function paretoFront(candidates: Candidate[]): Candidate[] {
	const sorted = [...candidates].sort((a, b) => a.wait - b.wait || a.dv - b.dv);
	const front: Candidate[] = [];
	let bestDv = Infinity;
	for (const c of sorted) {
		if (c.dv < bestDv) {
			front.push(c);
			bestDv = c.dv;
		}
	}
	return front;
}

/** The front's corner: nearest point to the best-of-both ideal, after scaling. */
function kneePoint(front: Candidate[]): Candidate {
	if (front.length <= 2) return front[front.length - 1];
	let dvMin = Infinity;
	let dvMax = -Infinity;
	let waitMin = Infinity;
	let waitMax = -Infinity;
	for (const c of front) {
		dvMin = Math.min(dvMin, c.dv);
		dvMax = Math.max(dvMax, c.dv);
		waitMin = Math.min(waitMin, c.wait);
		waitMax = Math.max(waitMax, c.wait);
	}
	const dvRange = dvMax - dvMin || 1;
	const waitRange = waitMax - waitMin || 1;
	let best = front[0];
	let bestScore = Infinity;
	for (const c of front) {
		const x = (c.dv - dvMin) / dvRange;
		const y = (c.wait - waitMin) / waitRange;
		const score = x * x + y * y;
		if (score < bestScore) {
			bestScore = score;
			best = c;
		}
	}
	return best;
}

function clamp(value: number, min: number, max: number): number {
	return value < min ? min : value > max ? max : value;
}

/**
 * Polish a grid cell by shrinking a local search around it. The grid's
 * resolution is coarse next to how sharply Δv varies near a window, so the
 * cell minimum can sit a few hundred m/s above the true one; successive
 * halving removes most of that gap for a few dozen extra solves.
 *
 * The search stays inside the grid — a candidate on an edge (usually the
 * cheapest, since a longer cruise keeps getting cheaper) would otherwise walk
 * off it, leaving a route the same-grid porkchop can't place. The deadline
 * bounds it more sharply still: cost falls off towards a later arrival, so an
 * unbounded polish would walk a route chosen for arriving in time straight
 * past its own deadline.
 */
function refine(
	departure: TravelBody,
	target: TravelBody,
	candidate: Candidate,
	grid: PorkchopGrid,
	options: RouteOptions,
	latestArriveJd: number
): Route | null {
	const seed = buildRoute(departure, target, candidate.departJd, candidate.tofDays, options);
	if (!seed) return null;
	let bestRoute: Route = seed;

	const departMin = grid.departJds[0];
	const departMax = grid.departJds[grid.departSteps - 1];
	const tofMin = grid.tofDays[0];
	const tofMax = grid.tofDays[grid.tofSteps - 1];

	let departSpan = grid.departSteps > 1 ? grid.departJds[1] - grid.departJds[0] : 0;
	let tofSpan = grid.tofSteps > 1 ? grid.tofDays[1] - grid.tofDays[0] : 0;

	for (let pass = 0; pass < 6; pass++) {
		departSpan /= 2;
		tofSpan /= 2;
		let improved: Route = bestRoute;
		for (const dDepart of [-departSpan, 0, departSpan]) {
			for (const dTof of [-tofSpan, 0, tofSpan]) {
				if (dDepart === 0 && dTof === 0) continue;
				const departJd = clamp(improved.departJd + dDepart, departMin, departMax);
				// Too late to make it even at the grid's shortest cruise.
				const tofCeil = Math.min(tofMax, latestArriveJd - departJd);
				if (tofCeil < tofMin) continue;
				const tof = clamp(improved.tofDays + dTof, tofMin, tofCeil);
				const route = buildRoute(departure, target, departJd, tof, options);
				if (route && route.totalDvKms < improved.totalDvKms) improved = route;
			}
		}
		bestRoute = improved;
	}
	return bestRoute;
}
