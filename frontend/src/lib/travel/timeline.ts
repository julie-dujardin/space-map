/**
 * A trip as the stretches and moments it is made of.
 *
 * The route already lists its own steps in order, and the Δv ladder reads off
 * that same list — so the timeline is built from the legs rather than from a
 * second idea of what happens on a trip. Nothing here needs the drawn geometry,
 * so a trajectory whose arc cannot be rebuilt still has a timeline.
 *
 * A leg that takes time is a **phase** and a leg that happens at an instant is
 * an **event**; `days` is what tells them apart, and the two are drawn
 * differently because they are different things — one is a stretch of the bar,
 * the other a point on it.
 *
 * Labels live in the component: everything here is structure, so it can be
 * tested without a locale.
 */

import { dateToJD, jdToDate } from '$lib/format/date';
import type { LegKind, Route } from '$lib/math/travel';

export interface TimelineEntry {
	/** Stable for a given trip, so the list can key on it. */
	id: string;
	kind: LegKind;
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
}

/**
 * The legs of `route` placed in time, in flight order.
 *
 * The dates come from accumulating each leg's duration off the departure, which
 * is the same arithmetic the route was priced with — so the last one ends on the
 * arrival date without being told to.
 */
export function buildTimeline(route: Route, nameFor: (bodyId: string) => string): TimelineEntry[] {
	const entries: TimelineEntry[] = [];
	const flybys = [...(route.flybys ?? [])];
	let jd = route.departJd;

	for (const [index, leg] of route.legs.entries()) {
		// Which end of the trip a leg happens at. A coast is at neither: that is
		// the whole of what a cruise is. Aerobraking counts as the arrival end —
		// it is months of passes through the destination's own atmosphere.
		const flyby = leg.kind === 'assist' ? flybys.shift() : undefined;
		const bodyId =
			leg.kind === 'ascent' || leg.kind === 'injection' || leg.kind === 'spiral-out'
				? route.departureId
				: leg.kind === 'capture' ||
					  leg.kind === 'aerobrake' ||
					  leg.kind === 'descent' ||
					  leg.kind === 'spiral-in'
					? route.targetId
					: (flyby?.bodyId ?? null);

		entries.push({
			id: `${index}:${leg.kind}`,
			kind: leg.kind,
			startJd: jd,
			endJd: jd + leg.days,
			days: leg.days,
			isPhase: leg.days > 0,
			bodyId,
			bodyName: bodyId ? nameFor(bodyId) : '',
			dvKms: leg.dvKms,
			altitudeKm: flyby?.altitudeKm,
			aerobraked: leg.aerobraked
		});
		jd += leg.days;
	}

	return entries;
}

/**
 * Where to look when an entry is picked.
 *
 * A place on the drawn arc wherever there is one — the whole point of a
 * trajectory is the line, and half the legs happen nowhere near a body. The
 * body is the fallback for a route whose geometry could not be rebuilt.
 */
export type TimelineFocus =
	| {
			kind: 'point';
			centerId: string;
			r: readonly [number, number, number];
			rangeKm: number;
			/** Follow the point where the camera already is instead of flying to it —
			 *  a dragged clock moves it every frame, and re-framing on each would be
			 *  an animation restarting sixty times a second. */
			track?: boolean;
	  }
	| { kind: 'body'; bodyId: string };

/**
 * Which entry the clock is on: the last one it has reached.
 *
 * Before the trip starts that is still the first — the timeline is a place on a
 * trip, and "not left yet" is the launch's own state rather than a thing of its
 * own to draw.
 */
export function entryIndexAt(entries: readonly TimelineEntry[], jd: number): number {
	if (entries.length === 0) return -1;
	let index = 0;
	for (let i = 0; i < entries.length; i++) {
		if (entries[i].startJd <= jd) index = i;
	}
	return index;
}

export type TickUnit = 'year' | 'month' | 'day' | 'hour';

export interface AxisTick {
	jd: number;
	/**
	 * The boundary the tick sits on, as a calendar date.
	 *
	 * Carried rather than derived back from `jd`: a Date through a Julian Date and
	 * out again can land a millisecond short, and a millisecond short of New Year
	 * is labelled with the wrong year.
	 */
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
	// the coarsest step rather than returning one that would draw hundreds.
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
 * Aligned to local calendar boundaries rather than to even fractions of the
 * span: the labels are read as dates, and a "2035" that does not sit on New
 * Year is worse than no tick. Local, not UTC, because that is the clock the
 * labels are formatted against.
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

	// Pick the unit off the spacing the ticks would want, not off the span: at six
	// ticks a 150-day trip wants a step of 25 days, which is a month rather than a
	// clumsy multiple of a day.
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
		// Count months from year zero so the alignment does not restart each year.
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
