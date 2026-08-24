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

import { ObjectType, type BodyData } from '$lib/types/objects';
import type { EndOrbit, TravelBody } from '$lib/math/travel';
import { HILL_STABLE_FRACTION, orbitPeriodHours, parkingAltitudeKm } from '$lib/math/travel';
import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
// Type-only: the modes are a term of the trip, and `trip.ts` is on every page
// load's path — it must not pull the kernel in behind this module.
import type { EndpointMode } from './trip';

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
	return { rotationHours, hillKm: travel.hillKm, isCraft: isCraft(body) };
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
function maxRadiusKm(facts: OrbitFacts): number {
	return facts.hillKm ? facts.hillKm * HILL_STABLE_FRACTION : Infinity;
}

/**
 * Every way this end can be met, in the order they are offered.
 *
 * `role` decides two things: only a destination can be flown past or arrived
 * at on a transfer orbit, and only a departure can be from a body with no
 * ground — which is why `hasSurface` is asked rather than assumed.
 *
 * A craft is met or passed and nothing else: it holds no orbit, has no ground
 * worth naming, and matching its state is the whole of arriving at one.
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
		const plane = kind === 'custom' ? options.incDeg : kind === 'stationary' ? 0 : null;
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

	if (facts.isCraft) {
		add('rendezvous', 'meet');
		if (target) add('flyby', 'pass');
		return out;
	}

	if (options.hasSurface) add('surface', 'land');
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

	// The one orbit the trip shapes itself: both ends inside what the body holds,
	// and the far one never under the near one, which would be the same ellipse
	// named backwards.
	const rPeriCustom = Math.min(R + Math.max(options.customAltKm, 1), rMax);
	const rApoCustom = Math.min(Math.max(R + (options.customApoAltKm ?? 0), rPeriCustom), rMax);
	if (rPeriCustom > R) add('custom', 'orbit', { rPeriKm: rPeriCustom, rApoKm: rApoCustom });

	if (target) add('flyby', 'pass');
	return out;
}

/**
 * Highest altitude a custom orbit may be put at, km — a third of the Hill
 * radius, or a hundred body radii where that is unknown.
 *
 * Deliberately not floored at the parking orbit: a small body can hold less
 * than 200 km of room, and a slider past what `orbitChoices` clamps to would
 * show one altitude while pricing another.
 */
export function maxCustomAltitudeKm(travel: TravelBody, facts: OrbitFacts): number {
	const cap = facts.hillKm ? maxRadiusKm(facts) : travel.radiusKm * 100;
	return Math.max(cap - travel.radiusKm, 1);
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
