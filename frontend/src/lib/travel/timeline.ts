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
