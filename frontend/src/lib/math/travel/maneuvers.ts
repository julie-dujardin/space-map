/**
 * Δv for the manoeuvres that bracket a transfer: getting off one body and
 * arriving at another.
 *
 * These are patched-conic estimates with published loss factors, not
 * trajectory-optimiser output. They are good to a few percent for the burns
 * that dominate a mission budget, which is what a comparison between
 * destinations needs. Every approximation is named in the constants module.
 */

import { equatorialTiltDeg, type TravelBody } from './body';
import type { Vec3 } from './vec3';
import {
	AEROBRAKING_RATE_KMS_PER_DAY,
	AEROCAPTURE_TRIM_KMS,
	AERO_MIN_PRESSURE_PA,
	AERO_PASS_ALTITUDE_KM,
	AERO_PASS_ALTITUDE_MAX_KM,
	AERO_PASS_PRESSURE_PA,
	ASCENT_DRAG_LOSS_CAP_KMS,
	ASCENT_DRAG_LOSS_KMS_PER_BAR,
	ASCENT_GRAVITY_LOSS_FRACTION,
	CAPTURE_APOAPSIS_RADII,
	PARKING_ALTITUDE_KM,
	POWERED_TOUCHDOWN_KMS
} from './constants';

/** Circular orbital speed at radius `rKm`, km/s. */
export function circularSpeed(mu: number, rKm: number): number {
	return Math.sqrt(mu / rKm);
}

/** Radius of the standard parking orbit about a body, km. */
export function parkingRadiusKm(body: TravelBody): number {
	return body.radiusKm + PARKING_ALTITUDE_KM;
}

/**
 * The bound orbit an end of a trip sits in — periapsis and apoapsis from the
 * centre, km. Equal radii are circular. Which orbit is asked for is a real term
 * of the trip, not a detail: a stationary orbit costs a third of a low one to
 * enter, and less again to leave from. Defaults to the parking orbit when none
 * is named.
 */
export interface EndOrbit {
	rPeriKm: number;
	rApoKm: number;
}

/** The parking orbit as an `EndOrbit`. */
export function parkingOrbit(body: TravelBody): EndOrbit {
	const r = parkingRadiusKm(body);
	return { rPeriKm: r, rApoKm: r };
}

/** The loose ellipse a capture burn drops into. */
export function captureOrbit(body: TravelBody): EndOrbit {
	return { rPeriKm: parkingRadiusKm(body), rApoKm: CAPTURE_APOAPSIS_RADII * body.radiusKm };
}

/** An orbit with its apoapsis never below its periapsis, whatever was asked
 *  for. Guards the vis-viva terms below against a reversed pair. */
function sane(orbit: EndOrbit): EndOrbit {
	return { rPeriKm: orbit.rPeriKm, rApoKm: Math.max(orbit.rApoKm, orbit.rPeriKm) };
}

/**
 * True when there is an envelope thick enough to fly a braking pass through.
 * Judged on the measured pressure, not whether anything was detected: Mercury
 * and the icy moons have a real reading, orders of magnitude too thin for drag
 * to repay a pass, so offering them aerocapture would be fiction. Quoted at the
 * datum whatever the body's shape, so a gas giant's 1 bar level qualifies it
 * the way its cloud tops never could.
 */
export function canAeroBrake(body: TravelBody): boolean {
	return (body.aeroPressurePa ?? 0) >= AERO_MIN_PRESSURE_PA;
}

/** Radius the atmospheric pass is flown at, km. */
export function aeroPassRadiusKm(body: TravelBody): number {
	return body.radiusKm + aeroPassAltitudeKm(body);
}

/**
 * How high above the datum the pass sits, km — where the body's own envelope
 * reaches the target pass pressure, clamped between the Mars-calibrated floor
 * and what fits under the parking convention.
 */
function aeroPassAltitudeKm(body: TravelBody): number {
	const { aeroPressurePa: pa, aeroScaleHeightKm: h } = body;
	if (!pa || !h) return AERO_PASS_ALTITUDE_KM;
	const derived = h * Math.log(pa / AERO_PASS_PRESSURE_PA);
	return Math.min(Math.max(derived, AERO_PASS_ALTITUDE_KM), AERO_PASS_ALTITUDE_MAX_KM);
}

/**
 * Where a trip meets the ground, and how tilted the plane it has to fly is.
 * Absent from a trip that never touches a surface, or one that does but has no
 * known site — those read as the eastward equatorial launch the estimates are
 * calibrated on.
 */
export interface SurfaceSite {
	/** Latitude of the pad or the landing site, degrees. */
	latDeg: number;
	/**
	 * How far the arc's asymptote lies out of the body's equator, degrees. The
	 * plane must hold it as well as reach the site, so the steeper of the two is
	 * what the ascent flies. Absent when the plan can't say, leaving latitude
	 * alone to set it.
	 */
	asymptoteTiltDeg?: number;
}

/**
 * One end of a trip as the ascent and descent estimates want it. `asymptote` is
 * the excess-velocity vector there — a direction the plane must hold as well as
 * reach the site. Null leaves latitude alone to set the plane, right for inside
 * a system, where an arc can be flown from a node.
 */
export function surfaceSite(
	body: TravelBody,
	latDeg: number | undefined,
	asymptote: Vec3 | null
): SurfaceSite | undefined {
	if (latDeg === undefined) return undefined;
	return {
		latDeg,
		asymptoteTiltDeg: asymptote ? equatorialTiltDeg(body, asymptote) : undefined
	};
}

/**
 * The surface speed an ascent from `site` does not get to keep, km/s. A launch
 * starts with the ground's own velocity, but only the part along the plane it
 * climbs into counts; writing the azimuth in terms of inclination collapses
 * that to ω·R·cos(i) — latitude only sets how low the plane can lie.
 *
 * Charges the shortfall against ω·R, not the credit: the ascents
 * {@link ascentDv} is calibrated on are eastward near-equatorial launches that
 * already keep nearly all of it, so the equator costs nothing extra and a
 * polar climb pays the full surface speed.
 */
export function planeTiltPenaltyKms(body: TravelBody, site?: SurfaceSite): number {
	const omega = Math.abs(body.spinRadPerSec ?? 0);
	if (!site || !(omega > 0)) return 0;
	const incDeg = Math.min(
		90,
		Math.max(Math.abs(site.latDeg), Math.abs(site.asymptoteTiltDeg ?? 0))
	);
	return omega * body.radiusKm * (1 - Math.cos(incDeg * (Math.PI / 180)));
}

/**
 * Δv from the surface to the parking orbit, km/s. Circular velocity plus
 * gravity/steering losses scaled by surface gravity, plus a drag term for
 * bodies with an atmosphere, capped because it's linear in pressure and Venus
 * would otherwise dominate on a coefficient only ever fitted near 1 bar. Where
 * the launch site is known, it also pays for the spin it can't use — see
 * {@link planeTiltPenaltyKms}.
 */
export function ascentDv(body: TravelBody, site?: SurfaceSite): number {
	const vCirc = circularSpeed(body.mu, parkingRadiusKm(body));
	const gravityLoss = ASCENT_GRAVITY_LOSS_FRACTION * circularSpeed(body.mu, body.radiusKm);
	const drag = Math.min(
		ASCENT_DRAG_LOSS_CAP_KMS,
		ASCENT_DRAG_LOSS_KMS_PER_BAR * (body.surfacePressureBar ?? 0)
	);
	return vCirc + gravityLoss + drag + planeTiltPenaltyKms(body, site);
}

/**
 * Speed at periapsis on the arc that leaves with excess speed `vInfKms`.
 * Everything either burn is priced from: a departure pays the difference
 * against the parking orbit's own speed, an arrival against whatever bound
 * orbit it's dropping into — letting an escape and an in-system transfer share
 * the rest of the model.
 */
export function periapsisSpeed(mu: number, rPeriKm: number, vInfKms: number): number {
	return Math.sqrt(vInfKms * vInfKms + (2 * mu) / rPeriKm);
}

/**
 * Δv to leave a circular parking orbit on a hyperbola with excess speed
 * `vInfKms`. The Oberth effect is why this is so much less than `vInf` itself.
 */
export function injectionDv(mu: number, rParkKm: number, vInfKms: number): number {
	return periapsisSpeed(mu, rParkKm, vInfKms) - circularSpeed(mu, rParkKm);
}

/**
 * Δv to drop from an arrival hyperbola into a bound orbit with periapsis
 * `rPeriKm` and apoapsis `rApoKm`. Passing `rApoKm = rPeriKm` gives circular
 * capture; a loose ellipse is far cheaper and is what real orbiters do first.
 */
export function captureDv(mu: number, rPeriKm: number, rApoKm: number, vInfKms: number): number {
	return Math.max(0, periapsisSpeed(mu, rPeriKm, vInfKms) - boundSpeed(mu, rPeriKm, rApoKm));
}

/** Speed at periapsis of a bound orbit between the two radii, km/s. */
function boundSpeed(mu: number, rPeriKm: number, rApoKm: number): number {
	return Math.sqrt((2 * mu) / rPeriKm - (2 * mu) / (rPeriKm + rApoKm));
}

/** Speed at periapsis of a named orbit, km/s — what a departure burn is measured
 *  against, and what a circular orbit's own speed collapses to. */
export function orbitPeriapsisSpeed(mu: number, orbit: EndOrbit): number {
	const { rPeriKm, rApoKm } = sane(orbit);
	return boundSpeed(mu, rPeriKm, rApoKm);
}

/** How long one revolution takes, hours. */
export function orbitPeriodHours(mu: number, orbit: EndOrbit): number {
	const { rPeriKm, rApoKm } = sane(orbit);
	const a = (rPeriKm + rApoKm) / 2;
	return (2 * Math.PI * Math.sqrt(a ** 3 / mu)) / 3600;
}

/**
 * Speed at `rKm` on the arc that is doing `vKms` at `rFromKm`, km/s. Straight
 * from conservation of energy, so it carries an arrival down to its
 * atmospheric pass depth without caring whether the arc is bound: a capture
 * ellipse and a hyperbola both keep ε = v²/2 − μ/r.
 */
export function speedAtRadius(mu: number, vKms: number, rFromKm: number, rKm: number): number {
	return Math.sqrt(Math.max(0, vKms * vKms + 2 * mu * (1 / rKm - 1 / rFromKm)));
}

/**
 * Δv to move periapsis between two radii, spent at the apoapsis they share,
 * km/s. Both ends of an atmospheric arrival are this burn: the one that drops
 * periapsis into the air, and the one that lifts it back out.
 */
export function periapsisRaiseDv(
	mu: number,
	rFromKm: number,
	rToKm: number,
	rApoKm: number
): number {
	return Math.abs(apoapsisSpeed(mu, rToKm, rApoKm) - apoapsisSpeed(mu, rFromKm, rApoKm));
}

/** Speed at apoapsis of a bound orbit between the two radii, km/s. */
function apoapsisSpeed(mu: number, rPeriKm: number, rApoKm: number): number {
	return Math.sqrt(Math.max(0, (2 * mu) / rApoKm - (2 * mu) / (rPeriKm + rApoKm)));
}

export type ArrivalMode = 'flyby' | 'capture' | 'low-orbit' | 'landing';

/**
 * Whether the atmosphere is used on arrival, and how — a different trade, not
 * two strengths of one. Aerocapture is a single pass doing the whole insertion
 * at once and has never been flown; aerobraking captures on the engine and
 * spends months letting drag walk the orbit down, as every Mars orbiter since
 * Global Surveyor has done.
 */
export type AeroAssist = 'none' | 'aerocapture' | 'aerobraking';

export interface ArrivalCost {
	/** Δv to reach the bound orbit, km/s. Zero for a flyby, and for the direct
	 *  entry that lands straight off the approach without ever being in one. */
	captureKms: number;
	/** Δv from that orbit down to the surface, km/s. Zero unless landing. */
	descentKms: number;
	/** True when an atmosphere absorbed part of the arrival. */
	aerobraked: boolean;
	/** Δv drag removed instead of the engine, km/s. */
	absorbedKms: number;
	/** How long it took to remove it, days. Zero for a single pass. */
	aerobrakeDays: number;
	/** Fastest the craft meets the atmosphere at, km/s; absent when it never does. */
	entrySpeedKms?: number;
}

/** Nothing happens on arrival: a flyby, and the base every other case starts from. */
const NO_ARRIVAL_COST: ArrivalCost = {
	captureKms: 0,
	descentKms: 0,
	aerobraked: false,
	absorbedKms: 0,
	aerobrakeDays: 0
};

/**
 * Δv to arrive at `body` in the requested way, given the hyperbolic excess
 * speed the transfer delivers and whether the atmosphere is asked to help.
 * `aero` is a request, not a description — a body with nothing to fly through
 * ignores it, so it's safe to leave set while the destination changes.
 */
export function arrivalCost(
	body: TravelBody,
	vInfKms: number,
	mode: ArrivalMode,
	aero: AeroAssist = 'none',
	orbit?: EndOrbit,
	site?: SurfaceSite
): ArrivalCost {
	// The approach is priced at the periapsis it is flown to, which is the one the
	// orbit asked for — arriving into a stationary orbit still dips low first.
	const rPeri = pricedArrivalOrbit(body, mode, orbit).rPeriKm;
	return arrivalCostFromSpeed(
		body,
		periapsisSpeed(body.mu, rPeri, vInfKms),
		mode,
		aero,
		orbit,
		site
	);
}

/**
 * The orbit an arrival ends in. A landing passes through the parking orbit
 * whatever was asked for — you don't stop in a stationary orbit on the way
 * down — and a flyby ends in no orbit at all, so both ignore the request.
 */
function pricedArrivalOrbit(body: TravelBody, mode: ArrivalMode, orbit?: EndOrbit): EndOrbit {
	if (mode === 'landing' || mode === 'flyby') return parkingOrbit(body);
	if (orbit) return sane(orbit);
	return mode === 'capture' ? captureOrbit(body) : parkingOrbit(body);
}

/**
 * The same arrival priced from the speed the approach actually carries at
 * periapsis, rather than from a hyperbolic excess. Coming back down to the body
 * you launched from — Moon to Earth — you're still bound to it, so there's no
 * excess speed to quote; the burn is just how much faster the transfer is
 * going than the target orbit.
 */
export function arrivalCostFromSpeed(
	body: TravelBody,
	vPeriKms: number,
	mode: ArrivalMode,
	aero: AeroAssist = 'none',
	orbit?: EndOrbit,
	site?: SurfaceSite
): ArrivalCost {
	if (mode === 'flyby') return NO_ARRIVAL_COST;

	const { mu } = body;
	const { rPeriKm: rPeri, rApoKm: rApo } = pricedArrivalOrbit(body, mode, orbit);
	const assisted = aero !== 'none' && canAeroBrake(body);

	// An atmosphere is the whole descent. Without one, landing is the ascent run
	// backwards, spin and all — it cancels speed against the same moving ground.
	// Under a parachute the air has already taken it.
	const descent =
		mode !== 'landing'
			? 0
			: assisted
				? POWERED_TOUCHDOWN_KMS
				: circularSpeed(mu, rPeri) +
					ASCENT_GRAVITY_LOSS_FRACTION * circularSpeed(mu, body.radiusKm) +
					planeTiltPenaltyKms(body, site);

	if (!assisted) {
		return {
			...NO_ARRIVAL_COST,
			captureKms: Math.max(0, vPeriKms - boundSpeed(mu, rPeri, rApo)),
			descentKms: descent
		};
	}

	const rEntry = aeroPassRadiusKm(body);
	// Below the pass altitude there is no arrival to model: the approach is
	// already inside the atmosphere, or the body is smaller than the allowance.
	if (!(rEntry < rPeri)) {
		return {
			...NO_ARRIVAL_COST,
			captureKms: Math.max(0, vPeriKms - boundSpeed(mu, rPeri, rApo)),
			descentKms: descent
		};
	}

	const vEntry = speedAtRadius(mu, vPeriKms, rPeri, rEntry);

	if (aero === 'aerocapture') {
		// Landing off the approach never enters an orbit at all — the pass that
		// would have captured the craft puts it on the ground instead. Viking and
		// every Mars lander since arrived this way.
		if (mode === 'landing') {
			return {
				captureKms: 0,
				descentKms: descent,
				aerobraked: true,
				absorbedKms: vEntry,
				aerobrakeDays: 0,
				entrySpeedKms: vEntry
			};
		}
		// One pass leaves the craft on an ellipse whose periapsis is still in the
		// air; all it then owes is lifting that periapsis back out at apoapsis.
		return {
			captureKms: periapsisRaiseDv(mu, rEntry, rPeri, rApo) + AEROCAPTURE_TRIM_KMS,
			descentKms: descent,
			aerobraked: true,
			absorbedKms: Math.max(0, vEntry - boundSpeed(mu, rEntry, rApo)),
			aerobrakeDays: 0,
			entrySpeedKms: vEntry
		};
	}

	// Aerobraking: capture on the engine into the loosest ellipse that is still
	// bound, drop periapsis into the air, let drag walk apoapsis down to the
	// orbit that was asked for, and lift periapsis back out at the end.
	const rApoLoose = CAPTURE_APOAPSIS_RADII * body.radiusKm;
	// Asking to aerobrake into the ellipse the engine captures into anyway is
	// asking for a campaign with nothing to do, so it is priced as the burn alone.
	if (!(rApoLoose > rApo)) {
		return {
			...NO_ARRIVAL_COST,
			captureKms: Math.max(0, vPeriKms - boundSpeed(mu, rPeri, rApo)),
			descentKms: descent
		};
	}
	const insertion = Math.max(0, vPeriKms - boundSpeed(mu, rPeri, rApoLoose));
	const walkIn = periapsisRaiseDv(mu, rPeri, rEntry, rApoLoose);
	const walkOut = periapsisRaiseDv(mu, rEntry, rPeri, rApo);
	// What drag has to remove: the difference the pass makes at the depth it is
	// flown at, between the orbit it starts on and the one it ends on.
	const absorbed = Math.max(0, boundSpeed(mu, rEntry, rApoLoose) - boundSpeed(mu, rEntry, rApo));

	return {
		captureKms: insertion + walkIn + walkOut,
		descentKms: descent,
		aerobraked: true,
		absorbedKms: absorbed,
		aerobrakeDays: absorbed / AEROBRAKING_RATE_KMS_PER_DAY,
		entrySpeedKms: speedAtRadius(mu, boundSpeed(mu, rPeri, rApoLoose), rPeri, rEntry)
	};
}

/**
 * Days the arrival still owes once the crossing is over — the aerobraking
 * campaign, where there is one, and nothing otherwise. Worth having on its own
 * because it's the same figure for every arc that ends the same way: what drag
 * removes is the gap between two bound orbits at the pass altitude, which
 * doesn't remember the approach speed. So a search can compute it once and
 * hold a whole grid to the same deadline without pricing an arrival per cell —
 * hence the placeholder speed below.
 */
export function arrivalCampaignDays(
	body: TravelBody,
	mode: ArrivalMode,
	aero: AeroAssist = 'none',
	orbit?: EndOrbit
): number {
	return arrivalCostFromSpeed(body, 0, mode, aero, orbit).aerobrakeDays;
}

export type DepartureMode = 'surface' | 'orbit';

/**
 * The orbit a trip is flown out of, or null when it starts on the ground.
 * Pairs with {@link endArrivalOrbit}: together they say which trip ends are
 * somewhere the craft orbits rather than stands or passes through, deciding
 * whether that end is a step of its own.
 */
export function endDepartureOrbit(
	body: TravelBody,
	mode: DepartureMode,
	orbit?: EndOrbit
): EndOrbit | null {
	if (mode !== 'orbit') return null;
	return orbit ? sane(orbit) : parkingOrbit(body);
}

/** The orbit a trip ends in, or null for a landing or a flyby — neither does. */
export function endArrivalOrbit(
	body: TravelBody,
	mode: ArrivalMode,
	orbit?: EndOrbit
): EndOrbit | null {
	if (mode === 'flyby' || mode === 'landing') return null;
	return pricedArrivalOrbit(body, mode, orbit);
}

/**
 * Δv to get from `body` onto a transfer needing excess speed `vInfKms`,
 * starting either from the ground or from an existing parking orbit.
 */
export function departureCost(
	body: TravelBody,
	vInfKms: number,
	mode: DepartureMode,
	orbit?: EndOrbit,
	site?: SurfaceSite
): { ascentKms: number; injectionKms: number } {
	// An ascent goes to the parking orbit and leaves from there: which orbit the
	// craft would otherwise have been sitting in is not a question a launch asks.
	const from = mode === 'surface' || !orbit ? parkingOrbit(body) : sane(orbit);
	return {
		ascentKms: mode === 'surface' ? ascentDv(body, site) : 0,
		// Spent at periapsis, where the Oberth effect is largest — and where an
		// elliptical parking orbit is already moving faster than a circular one, so
		// leaving from one is cheaper still.
		injectionKms: Math.max(
			0,
			periapsisSpeed(body.mu, from.rPeriKm, vInfKms) - orbitPeriapsisSpeed(body.mu, from)
		)
	};
}

/** Characteristic energy, km²/s² — the figure launch vehicles are rated against. */
export function characteristicEnergy(vInfKms: number): number {
	return vInfKms * vInfKms;
}
