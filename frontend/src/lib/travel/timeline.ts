/**
 * A trip as the stretches and moments it is made of.
 *
 * The route already lists its own steps in order, and the Δv ladder reads off
 * that same list — so the timeline is built from the legs rather than a second
 * idea of what happens on a trip. Nothing here needs the drawn geometry, so a
 * trajectory whose arc can't be rebuilt still has a timeline.
 *
 * A leg that takes time is a **phase**, one at an instant is an **event**;
 * `days` is what tells them apart, drawn differently because they're
 * different things — one a stretch of the bar, the other a point on it.
 *
 * Labels live in the component: everything here is structure, testable
 * without a locale.
 */

import { dateToJD, jdToDate } from '$lib/format/date';
import { SECONDS_PER_DAY } from '$lib/format/duration';
import type { LegKind, Route, TravelBody } from '$lib/math/travel';
// Deep import, not the kernel's index: this module is on the map's own chunk,
// and the index carries Lambert, the porkchop and the vehicle catalogue.
import { endArrivalOrbit, endDepartureOrbit, type EndOrbit } from '$lib/math/travel/maneuvers';

/** What a step of the trip is: the legs of the route, plus the two ends that
 *  aren't legs at all — the orbit flown out of, and the one left in. Nothing
 *  is spent and no time passes at either; they're where the trip starts and
 *  stops, which the legs alone never say. */
export type TimelineKind = LegKind | 'start-orbit' | 'final-orbit';

export interface TimelineEntry {
	/** Stable for a given trip, so the list can key on it. */
	id: string;
	kind: TimelineKind;
	startJd: number;
	/** Equal to `startJd` for an event. */
	endJd: number;
	days: number;
	/** A stretch of the trip rather than a moment in it. */
	isPhase: boolean;
	/** The body it happens at, where there is one. Null out in the cruise. */
	bodyId: string | null;
	/** What that body is called — localized, and the named place rather than the
	 *  planet when an end is one. Empty where there is no body. */
	bodyName: string;
	dvKms: number;
	/** Height of closest approach, km — swing-bys only. */
	altitudeKm?: number;
	/** The atmosphere did the braking rather than the engine. */
	aerobraked?: boolean;
	/** Δv the atmosphere removed on this leg, km/s — the aero legs only. */
	absorbedKms?: number;
	/** The orbit an end of the trip is, carried with the radius of the body it
	 *  goes round so an altitude can be read off it. The two orbit entries only. */
	orbit?: { shape: EndOrbit; bodyRadiusKm: number };
}

/**
 * The legs of `route` placed in time, in flight order, bracketed by the orbits
 * at either end where those ends are orbits.
 *
 * Dates come from accumulating each leg's duration off the departure — the
 * same arithmetic the route was priced with — so the last one ends on the
 * arrival date without being told to.
 *
 * `bodies` is what the two ends are derived from; without it the trip is its
 * legs alone, what a timeline built before the bodies land shows.
 */
/**
 * Dates the drawn geometry knows better than the priced legs do. Pricing puts
 * every arrival instant on the crossing's own date, but the drawn trip spreads
 * them out — the burn at the real periapsis, the raise at the apoapsis after
 * the pass, touchdown a coast and a fall past the arrival — and a card dated
 * where its line is drawn is what makes picking it show that place.
 */
export interface DrawnDates {
	liftoffJd?: number;
	touchdownJd?: number;
	/** Where the drawn crossing takes over from the departure's own escape. */
	cruiseJd?: number;
	/** The arrival's real periapsis — the capture burn, or the braking pass. */
	captureJd?: number;
	/** The engine's raise, at the drawn apoapsis after the atmosphere's part. */
	raiseJd?: number;
}

/** Half a revolution of `orbit`, days — how far outside the trip its two
 *  bracketing orbit cards sit, so they date apart from the burns at them. */
function halfOrbitDays(orbit: EndOrbit, mu: number): number {
	if (!(mu > 0)) return 0;
	return (Math.PI * Math.sqrt(((orbit.rPeriKm + orbit.rApoKm) / 2) ** 3 / mu)) / SECONDS_PER_DAY;
}

export function buildTimeline(
	route: Route,
	nameFor: (bodyId: string) => string,
	bodies?: { departure: TravelBody; target: TravelBody } | null,
	drawn?: DrawnDates | null
): TimelineEntry[] {
	const entries: TimelineEntry[] = [];
	const flybys = [...(route.flybys ?? [])];
	let jd = route.departJd;

	/** An end of the trip: a place, not something that happens, so it costs
	 *  nothing and takes no time. */
	const endEntry = (
		kind: 'start-orbit' | 'final-orbit',
		bodyId: string,
		orbit: EndOrbit,
		body: TravelBody,
		at: number
	): TimelineEntry => ({
		id: kind,
		kind,
		startJd: at,
		endJd: at,
		days: 0,
		isPhase: false,
		bodyId,
		bodyName: nameFor(bodyId),
		dvKms: 0,
		orbit: { shape: orbit, bodyRadiusKm: body.radiusKm }
	});

	const start =
		bodies && endDepartureOrbit(bodies.departure, route.departureMode, route.departureOrbit);
	if (bodies && start) {
		// Half a revolution before the injection: in the orbit, not yet leaving —
		// dated apart from the burn so the two cards are different moments.
		entries.push(
			endEntry(
				'start-orbit',
				route.departureId,
				start,
				bodies.departure,
				jd - halfOrbitDays(start, bodies.departure.mu)
			)
		);
	}
	let cruiseTaken = false;

	for (const [index, leg] of route.legs.entries()) {
		// Which end of the trip a leg happens at. A coast is at neither — that's
		// the whole of what a cruise is. Aerobraking counts as the arrival end:
		// months of passes through the destination's own atmosphere.
		const flyby = leg.kind === 'assist' ? flybys.shift() : undefined;
		const bodyId =
			leg.kind === 'ascent' || leg.kind === 'injection' || leg.kind === 'spiral-out'
				? route.departureId
				: leg.kind === 'capture' ||
					  leg.kind === 'rendezvous' ||
					  leg.kind === 'aero-pass' ||
					  leg.kind === 'aerobrake' ||
					  leg.kind === 'raise' ||
					  leg.kind === 'descent' ||
					  leg.kind === 'spiral-in'
					? route.targetId
					: (flyby?.bodyId ?? null);

		// The drawn dates replace the priced ones on the cards they know better;
		// the accumulator stays priced, so nothing else moves. Only the first
		// cruise leaves the departure body — a swing-by's later ones don't.
		const firstCruise = leg.kind === 'cruise' && !cruiseTaken;
		if (leg.kind === 'cruise') cruiseTaken = true;
		const at =
			leg.kind === 'ascent' && drawn?.liftoffJd !== undefined
				? drawn.liftoffJd
				: leg.kind === 'descent' && drawn?.touchdownJd !== undefined
					? drawn.touchdownJd
					: firstCruise && drawn?.cruiseJd !== undefined
						? drawn.cruiseJd
						: (leg.kind === 'capture' || leg.kind === 'rendezvous' || leg.kind === 'aero-pass') &&
							  drawn?.captureJd !== undefined
							? drawn.captureJd
							: leg.kind === 'raise' && drawn?.raiseJd !== undefined
								? drawn.raiseJd
								: jd;
		entries.push({
			id: `${index}:${leg.kind}`,
			kind: leg.kind,
			startJd: at,
			// A phase's far end stays priced, so a re-dated start never pushes the
			// legs after it; an instant is over the moment it happens.
			endJd: leg.days > 0 ? jd + leg.days : at,
			days: leg.days,
			isPhase: leg.days > 0,
			bodyId,
			bodyName: bodyId ? nameFor(bodyId) : '',
			dvKms: leg.dvKms,
			altitudeKm: flyby?.altitudeKm,
			aerobraked: leg.aerobraked,
			absorbedKms: leg.absorbedKms
		});
		jd += leg.days;
	}

	// After the last leg, not the arrival date: an aerobraking campaign is
	// months of not being in the orbit yet. Half a revolution past the burn
	// that entered it — settled in the orbit, a moment of its own.
	const final = bodies && endArrivalOrbit(bodies.target, route.arrivalMode, route.targetOrbit);
	if (bodies && final) {
		const entered = drawn?.raiseJd ?? drawn?.captureJd ?? jd;
		entries.push(
			endEntry(
				'final-orbit',
				route.targetId,
				final,
				bodies.target,
				Math.max(entered, jd) + halfOrbitDays(final, bodies.target.mu)
			)
		);
	}

	return entries;
}

/** Where to look when an entry is picked: a place on the drawn arc wherever
 *  there is one, since half the legs happen nowhere near a body. The body is
 *  the fallback for a route whose geometry couldn't be rebuilt. */
export type TimelineFocus =
	| {
			kind: 'point';
			centerId: string;
			r: readonly [number, number, number];
			/** Move the point now rather than swinging the pivot onto it: a dragged
			 *  clock moves it every frame, and a swing per frame is an animation
			 *  restarting sixty times a second. */
			track?: boolean;
	  }
	| { kind: 'body'; bodyId: string };

/** Which entry the clock is on: the last one it has reached. Before the trip
 *  starts that is still the first — "not left yet" is the launch's own state,
 *  not a thing of its own to draw. */
export function entryIndexAt(entries: readonly TimelineEntry[], jd: number): number {
	if (entries.length === 0) return -1;
	let index = 0;
	for (let i = 0; i < entries.length; i++) {
		if (entries[i].startJd <= jd) index = i;
	}
	return index;
}

/** Where a step of `delta` entries lands from `jd`, clamped to the trip.
 *  Stepping back from inside a phase means that phase's start, not the entry
 *  before it — the clock is past the entry, not on it. */
export function stepEntryIndex(
	entries: readonly TimelineEntry[],
	jd: number,
	delta: number
): number {
	const at = entryIndexAt(entries, jd);
	if (at < 0) return 0;
	const onEntry = entries[at].startJd === jd;
	const next = delta < 0 && !onEntry ? at : at + delta;
	return Math.min(entries.length - 1, Math.max(0, next));
}

export type TickUnit = 'year' | 'month' | 'day' | 'hour';

export interface AxisTick {
	jd: number;
	/** The boundary the tick sits on, as a calendar date. Carried rather than
	 *  derived back from `jd`: a Date round-tripped through a Julian Date can land
	 *  a millisecond short, and that's enough to mislabel the year. */
	date: Date;
	unit: TickUnit;
}

const YEAR_STEPS = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500] as const;
const MONTH_STEPS = [1, 2, 3, 6] as const;
const DAY_STEPS = [1, 2, 5, 10, 15, 20, 25] as const;
const HOUR_STEPS = [1, 2, 3, 6, 12] as const;

const DAYS_PER_YEAR = 365.25;
const DAYS_PER_MONTH = DAYS_PER_YEAR / 12;
const HOURS_PER_DAY = 24;

/** The finest step from `ladder` that keeps the count under `maxTicks`. */
function stepFor(ladder: readonly number[], span: number, maxTicks: number): number {
	for (const step of ladder) {
		if (span / step <= maxTicks) return step;
	}
	// Past the end of the ladder — a trip measured in millennia. Keep decupling
	// the coarsest step rather than drawing hundreds of ticks.
	let step = ladder[ladder.length - 1];
	while (span / step > maxTicks) step *= 10;
	return step;
}

/** Midnight local time on 1 January of `year`. Built by setter, since the Date
 *  constructor maps years under 100 into the 1900s. */
function atYear(year: number): Date {
	const date = new Date(2000, 0, 1);
	date.setFullYear(year, 0, 1);
	date.setHours(0, 0, 0, 0);
	return date;
}

/** Midnight local time on the first of `month` (0-based, may run outside 0-11). */
function atMonth(year: number, month: number): Date {
	const date = atYear(year);
	date.setMonth(month);
	return date;
}

/**
 * Dates to label the axis with, between `startJd` and `endJd`.
 *
 * Aligned to local calendar boundaries rather than even fractions of the
 * span: the labels are read as dates, and a "2035" not sitting on New Year is
 * worse than no tick. Local, not UTC, since that's the clock they're
 * formatted against.
 */
export function axisTicks(startJd: number, endJd: number, maxTicks = 6): AxisTick[] {
	const spanDays = endJd - startJd;
	if (!(spanDays > 0) || !Number.isFinite(spanDays) || maxTicks < 1) return [];

	const start = jdToDate(startJd);
	const end = jdToDate(endJd);
	const ticks: AxisTick[] = [];
	const push = (date: Date, unit: TickUnit) => {
		const jd = dateToJD(date);
		if (jd >= startJd && jd <= endJd) ticks.push({ jd, date, unit });
	};

	// Pick the unit off the spacing the ticks would want, not off the span: at
	// six ticks a 150-day trip wants a 25-day step, which is a month rather than
	// a clumsy multiple of a day.
	const stepDays = spanDays / maxTicks;
	if (stepDays >= DAYS_PER_MONTH * 11) {
		const step = stepFor(YEAR_STEPS, spanDays / DAYS_PER_YEAR, maxTicks);
		const first = Math.ceil(start.getFullYear() / step) * step;
		for (let year = first; ; year += step) {
			const date = atYear(year);
			if (date > end) break;
			push(date, 'year');
		}
	} else if (stepDays >= 25) {
		const step = stepFor(MONTH_STEPS, spanDays / DAYS_PER_MONTH, maxTicks);
		// Count months from year zero so alignment doesn't restart each year.
		const startIndex = start.getFullYear() * 12 + start.getMonth();
		for (let index = Math.ceil(startIndex / step) * step; ; index += step) {
			const date = atMonth(Math.floor(index / 12), index % 12);
			if (date > end) break;
			push(date, 'month');
		}
	} else if (stepDays >= 0.5) {
		const step = stepFor(DAY_STEPS, spanDays, maxTicks);
		const date = new Date(start);
		date.setHours(0, 0, 0, 0);
		if (date < start) date.setDate(date.getDate() + 1);
		for (; date <= end; date.setDate(date.getDate() + step)) push(new Date(date), 'day');
	} else {
		const step = stepFor(HOUR_STEPS, spanDays * HOURS_PER_DAY, maxTicks);
		const date = new Date(start);
		date.setMinutes(0, 0, 0);
		while (date < start || date.getHours() % step !== 0) date.setHours(date.getHours() + 1);
		for (; date <= end; date.setHours(date.getHours() + step)) push(new Date(date), 'hour');
	}

	return ticks;
}
