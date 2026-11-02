/**
 * Which orbits a body can be met in, and what each one is.
 *
 * Derived from the body rather than listed per planet: a stationary orbit
 * exists where the synchronous radius clears the ground and still sits inside
 * the region the body holds. That one rule drops it for Venus (day longer than
 * the space it controls) and for every tidally locked moon at once —
 * synchronous works out at 3^(1/3) = 1.44 Hill radii for all of them.
 *
 * Only shapes the kernel prices differently are offered, and the shape itself is
 * left to the custom orbit: the named orbits are named for a shape, so one of
 * them flown in another plane, or with its two ends set apart, would be two
 * entries under one name. The stationary orbit is the exception, since it is
 * named for a shape it can only hold in one plane.
 */

import { isExtrasolarObjectId } from '$lib/fetch/extrasolar/ids';
import { ObjectType, type BodyData } from '$lib/types/objects';
import type { AeroAssist, EndOrbit, Route, TravelBody } from '$lib/math/travel';
import {
	arrivalCost,
	crossingAero,
	departureCost,
	HILL_STABLE_FRACTION,
	orbitPeriodHours,
	parkingAltitudeKm,
	rapidityOfSpeed,
	STAR_REACH_KM,
	starPassKms
} from '$lib/math/travel';
import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
import { systemOf } from '$lib/state/nav-end';
import { DEFAULT_CUSTOM_ALT_KM, type EndpointMode } from './trip';

const HOURS_PER_DAY = 24;

/** Apoapsis of the loose capture ellipse, in body radii. Mirrors the kernel's
 *  own constant — the ellipse offered here is the one it prices. */
const CAPTURE_APOAPSIS_RADII = 20;

/** How high a "highly elliptical" orbit reaches, as a share of synchronous. */
const HEO_APOAPSIS_SYNC_RATIO = 1.5;

/** What the body itself contributes to which orbits exist. */
export interface OrbitFacts {
	/** Sidereal rotation, hours. Absent when the spin is not published. */
	rotationHours?: number;
	/** How far the body holds an orbit against its primary, km. */
	hillKm?: number;
	/** True for something built rather than found. Nothing orbits a spacecraft:
	 *  it is met or passed, which is all {@link orbitChoices} then offers. */
	isCraft?: boolean;
	/** True for a star, the Sun among them. It has no ground and no Hill radius,
	 *  so a custom orbit reaches {@link STAR_REACH_KM} from it. */
	isStar?: boolean;
	/** True on a trip between two systems. A star there is held at or passed, or
	 *  takes a custom orbit. Inside its own system every star is met as the Sun is. */
	crossing?: boolean;
	/** True for a body with no known pole: a star other than the Sun, or a planet
	 *  of one. An orbit there has no plane to name, and the price leaves it free. */
	noPole?: boolean;
}

/**
 * Rotation and Hill radius for a body. Spin comes from the IAU prime-meridian
 * rate the orientation bundle already carries; the Hill radius rides on the
 * travel body, where `toTravelBody` put it.
 */
export function orbitFacts(
	body: BodyData,
	travel: TravelBody,
	detail: GlobalObjectData | null | undefined
): OrbitFacts {
	const spinDegPerDay = detail?.orientation?.w1;
	const rotationHours =
		spinDegPerDay && Math.abs(spinDegPerDay) > 0
			? (HOURS_PER_DAY * 360) / Math.abs(spinDegPerDay)
			: undefined;
	return {
		rotationHours,
		hillKm: travel.hillKm,
		isCraft: isCraft(body),
		isStar: systemOf(body.id) === body.id,
		noPole: isExtrasolarObjectId(body.id)
	};
}

/**
 * Whether the object is a craft — a spacecraft or a piece of one. Its own
 * gravity is nothing anything could hold an orbit against, so it is a place to
 * meet rather than a body to go round.
 */
export function isCraft(body: BodyData): boolean {
	return body.objectType === ObjectType.SPACECRAFT || body.objectType === ObjectType.DEBRIS;
}

/**
 * Whether there is ground to land on.
 *
 * A gas giant is the one case that has to be told apart: it has the thickest
 * atmosphere in the system and no surface under it, which the export says by
 * quoting its pressure at a level that isn't a datum — envelope known, surface
 * pressure not. A body whose detail hasn't loaded claims ground, which is what
 * every rocky body turns out to have.
 */
export function hasGround(travel: TravelBody): boolean {
	return !(travel.hasAtmosphere === true && travel.surfacePressureBar === undefined);
}

export type OrbitGroup = 'meet' | 'land' | 'orbit' | 'pass';

/** What the trip asks of an end, beyond the body itself. */
export interface OrbitOptions {
	hasSurface: boolean;
	/** Periapsis altitude of the custom orbit, km. */
	customAltKm: number;
	/** Apoapsis altitude of it, km. Absent, or under the periapsis, is circular
	 *  — the only shape the custom orbit had before it had two ends. */
	customApoAltKm?: number;
	/** Plane the custom orbit is flown in, degrees to the body's equator. Null
	 *  leaves it free, which is how the named orbits are offered. */
	incDeg?: number | null;
	/** Where its periapsis sits, degrees round from the equator crossing. Null
	 *  leaves the crossing free to be at the high point, which is where a plane
	 *  is cheapest to turn. */
	argPeriDeg?: number | null;
}

export interface OrbitChoice {
	kind: EndpointMode;
	group: OrbitGroup;
	/** The orbit itself. Absent for a landing or a flyby, which are not one. */
	orbit?: EndOrbit;
	/** Periapsis and apoapsis altitude above the surface, km. */
	periAltKm?: number;
	apoAltKm?: number;
	periodHours?: number;
}

/** Radius of the orbit that keeps pace with the body's own turn, km. */
export function synchronousRadiusKm(mu: number, rotationHours: number): number {
	const t = rotationHours * 3600;
	return Math.cbrt((mu * t * t) / (4 * Math.PI * Math.PI));
}

/**
 * Altitude a low orbit sits at, km.
 *
 * The kernel's own parking altitude, so the orbit offered here is the one it
 * prices and draws.
 */
export function lowOrbitAltitudeKm(travel: TravelBody, facts: OrbitFacts): number {
	return parkingAltitudeKm(travel.radiusKm, facts.hillKm);
}

/** The highest radius still bound to the body, km. Unknown Hill radius means no
 *  cap: an orbit is offered on what is known rather than withheld on what is not. */
export function maxRadiusKm(facts: OrbitFacts): number {
	if (facts.isStar) return STAR_REACH_KM;
	return facts.hillKm ? facts.hillKm * HILL_STABLE_FRACTION : Infinity;
}

/**
 * The highest radius of the custom orbit, km. The reader asks for this orbit, so
 * it can go past what the body holds. It is {@link maxRadiusKm} where that clears
 * the low orbit, else the whole Hill radius, else the low orbit itself. A body
 * with no room then offers a row with no travel instead of no row.
 */
export function customReachKm(travel: TravelBody, facts: OrbitFacts): number {
	const rLow = travel.radiusKm + lowOrbitAltitudeKm(travel, facts);
	const stable = maxRadiusKm(facts);
	return stable > rLow ? stable : Math.max(facts.hillKm ?? 0, rLow);
}

/**
 * Every way this end can be met, in the order they are offered.
 *
 * Only a destination can be flown past or reached on a transfer orbit.
 * `hasSurface` says whether the body has ground to land on or leave from. A
 * craft is met or passed, and has no orbit and no ground. A star has no ground.
 * Between two systems it is met, passed or orbited at will. Inside its own
 * system it is met as any other body is. A star with no μ has no orbit to price.
 */
export function orbitChoices(
	travel: TravelBody,
	facts: OrbitFacts,
	role: 'origin' | 'target',
	options: OrbitOptions
): OrbitChoice[] {
	const target = role === 'target';
	const R = travel.radiusKm;
	const rMax = maxRadiusKm(facts);
	const rLow = R + lowOrbitAltitudeKm(travel, facts);
	const park: EndOrbit = { rPeriKm: rLow, rApoKm: rLow };
	const out: OrbitChoice[] = [];

	const add = (kind: EndpointMode, group: OrbitGroup, shape?: EndOrbit) => {
		if (!shape) {
			out.push({ kind, group });
			return;
		}
		// A stationary orbit hangs over one point, which it can only do from the
		// equator, so it names its plane where the other named orbits leave it
		// free. On a tilted body that plane is not the one arrivals come in on,
		// and the turn into it is most of what the orbit costs.
		const named = facts.noPole ? null : options.incDeg;
		const plane = kind === 'custom' ? named : kind === 'stationary' ? 0 : null;
		// An angle round from the equator crossing, so it goes to the one orbit
		// that has a plane to measure it from and two ends to make it an angle.
		const arg =
			kind === 'custom' && plane != null && shape.rApoKm > shape.rPeriKm
				? options.argPeriDeg
				: null;
		const orbit: EndOrbit = {
			...shape,
			...(plane == null ? {} : { incDeg: plane }),
			...(arg == null ? {} : { argPeriDeg: arg })
		};
		out.push({
			kind,
			group,
			orbit,
			periAltKm: orbit.rPeriKm - R,
			apoAltKm: orbit.rApoKm - R,
			periodHours: orbitPeriodHours(travel.mu, orbit)
		});
	};

	// The one orbit the trip shapes itself. The far end is never under the near
	// end, because that is the same ellipse named backwards.
	const addCustom = () => {
		const reach = customReachKm(travel, facts);
		const rPeriCustom = Math.min(R + Math.max(options.customAltKm, 1), reach);
		const rApoCustom = Math.min(Math.max(R + (options.customApoAltKm ?? 0), rPeriCustom), reach);
		if (travel.mu > 0) add('custom', 'orbit', { rPeriKm: rPeriCustom, rApoKm: rApoCustom });
	};

	if (facts.isCraft) {
		add('rendezvous', 'meet');
		if (target) add('flyby', 'pass');
		return out;
	}
	if (facts.isStar && (facts.crossing || !(travel.mu > 0))) {
		add('rendezvous', 'meet');
		addCustom();
		if (target) add('flyby', 'pass');
		return out;
	}

	if (options.hasSurface && !facts.isStar) add('surface', 'land');
	if (target) {
		const rCapture = Math.min(CAPTURE_APOAPSIS_RADII * R, rMax);
		if (rCapture > rLow) add('elliptical', 'orbit', { rPeriKm: rLow, rApoKm: rCapture });
	}
	add('low-orbit', 'orbit', park);

	const rSync = facts.rotationHours
		? synchronousRadiusKm(travel.mu, facts.rotationHours)
		: undefined;
	// A synchronous orbit underground, or outside what the body holds, is not one.
	if (rSync !== undefined && rSync > rLow && rSync < rMax) {
		const rSemi = rSync / Math.cbrt(4);
		if (rSemi > rLow) add('semi-sync', 'orbit', { rPeriKm: rSemi, rApoKm: rSemi });
		add('stationary', 'orbit', { rPeriKm: rSync, rApoKm: rSync });
		if (target) add('transfer', 'orbit', { rPeriKm: rLow, rApoKm: rSync });
		const rHeo = Math.min(rSync * HEO_APOAPSIS_SYNC_RATIO, rMax);
		if (rHeo > rLow) add('heo', 'orbit', { rPeriKm: rLow, rApoKm: rHeo });
	}

	addCustom();

	if (target) add('flyby', 'pass');
	return out;
}

/**
 * Highest altitude a custom orbit may be put at, km: what {@link customReachKm}
 * gives, or a hundred body radii where a body has no such limit. A slider past
 * the reach would show one altitude and price another, so a body with little
 * room gets a short slider.
 */
export function maxCustomAltitudeKm(travel: TravelBody, facts: OrbitFacts): number {
	const reach = customReachKm(travel, facts);
	return (Number.isFinite(reach) ? reach : travel.radiusKm * 100) - travel.radiusKm;
}

/** Share of a star's radius that the custom orbit's control starts at. Under it a
 *  height says nothing that the star's own surface does not. */
const STAR_FLOOR_RADII = 0.01;

/** Lowest altitude the control for a custom orbit gives, km. It spans ten orders of
 *  magnitude at a star, and it has only so many steps. It never starts above the
 *  altitude the row opens on, or above the top of the control. */
export function minCustomAltitudeKm(travel: TravelBody, facts: OrbitFacts): number {
	const floor = facts.isStar
		? Math.max(Math.min(travel.radiusKm * STAR_FLOOR_RADII, DEFAULT_CUSTOM_ALT_KM), 1)
		: 1;
	return Math.min(floor, maxCustomAltitudeKm(travel, facts));
}

/** Slider steps for each factor of ten of altitude. */
const STEPS_PER_DECADE = 175;

/** Under this top altitude a slider sets tenths of a kilometre, which a link
 *  keeps. Whole kilometres leave a short range with one or two places. */
const FINE_SLIDER_KM = 100;

/** A slider's altitudes, with `steps` positions above 0. */
export interface AltitudeScale {
	steps: number;
	position(km: number): number;
	altitude(position: number): number;
}

/**
 * Where an altitude sits on its slider, and back again.
 *
 * The scale is geometric. What a body holds spans five orders of magnitude at
 * Earth and ten at a star, so a step is a share of the height and not a number of
 * kilometres. A 600 km perigee and a 39750 km apogee can then both be set by hand.
 * The steps go by factors of ten, so a wide scale keeps the fineness of a narrow
 * one. A range with no width has no steps, and its one position is its one altitude.
 */
export function altitudeScale(minKm: number, maxKm: number): AltitudeScale {
	const ratio = maxKm / minKm;
	const steps = ratio > 1 ? Math.round(STEPS_PER_DECADE * Math.log10(ratio)) : 0;
	const perKm = maxKm < FINE_SLIDER_KM ? 10 : 1;
	return {
		steps,
		position(km) {
			if (steps === 0) return 0;
			const share = Math.log(Math.max(km, minKm) / minKm) / Math.log(ratio);
			return Math.round(steps * Math.min(share, 1));
		},
		altitude(position) {
			if (steps === 0) return minKm;
			return Math.round(minKm * ratio ** (position / steps) * perKm) / perKm;
		}
	};
}

/**
 * What `choice` would cost at this end, on `route`, km/s. A route between two
 * systems keeps real speeds, and every cost takes a rapidity figure. Null for a
 * choice with no price of its own.
 */
export function choicePriceKms(
	route: Route,
	body: TravelBody,
	role: 'origin' | 'target',
	choice: OrbitChoice,
	aero: AeroAssist,
	isStar: boolean
): number | null {
	const crossing = route.interstellar !== undefined;
	const speed = role === 'target' ? route.vInfArrKms : route.vInfDepKms;
	const excess = crossing ? rapidityOfSpeed(speed) : speed;
	if (choice.kind === 'rendezvous') {
		// A hold at a star is an orbit, as the crossing prices it.
		if (crossing && isStar) return starPassKms(body, body.mu, excess);
		// Meeting a craft is cancelling the speed you close on it with, which no
		// orbit enters into — so it is priced from the arc alone.
		return role === 'target'
			? arrivalCost(body, excess, 'rendezvous').captureKms
			: departureCost(body, excess, 'rendezvous').injectionKms;
	}
	if (!choice.orbit) return null;
	if (role === 'target') {
		const mode = choice.kind === 'elliptical' ? 'capture' : 'low-orbit';
		const air = crossing ? crossingAero(aero, excess) : aero;
		return arrivalCost(body, excess, mode, air, choice.orbit).captureKms;
	}
	return departureCost(body, excess, 'orbit', choice.orbit).injectionKms;
}

/** `mode` where `list` holds it. Else the low orbit where one is offered, and
 *  otherwise whatever is: a craft holds none and is cast off from instead, and on
 *  a same-body trip the low orbit is sometimes the end the craft is already at. */
export function settledMode(list: readonly OrbitChoice[], mode: EndpointMode): EndpointMode {
	if (list.some((c) => c.kind === mode)) return mode;
	return list.find((c) => c.kind === 'low-orbit')?.kind ?? list[0].kind;
}

/** The orbit a kind names, or undefined where it names none. */
export function orbitFor(
	kind: EndpointMode,
	travel: TravelBody,
	facts: OrbitFacts,
	role: 'origin' | 'target',
	options: OrbitOptions
): EndOrbit | undefined {
	return orbitChoices(travel, facts, role, options).find((c) => c.kind === kind)?.orbit;
}
