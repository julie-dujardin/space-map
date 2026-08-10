/**
 * What a drive that pushes for months at a time flies instead of a transfer
 * orbit.
 *
 * An ion engine cannot make the burns a Lambert arc is built from: a kilometre
 * per second takes Dawn's four months, so there is no instant for an impulse to
 * happen at and no coast between two of them. What it flies is a spiral — out of
 * the well it starts in, round the Sun while the orbit is slowly reshaped, and
 * down into the well at the far end.
 *
 * The model is Edelbaum's: a thrust held continuously, keeping the orbit
 * circular while its size and plane change together. The cost is then a triangle
 * of velocities and the duration is the rocket equation run at constant thrust.
 * It is the standard first cut at a low-thrust transfer, and it is a lower bound
 * on both figures — a real trajectory buys its phasing with coast arcs this does
 * not charge for, and loses a little to a spiral that is never quite circular.
 *
 * Three things fall out of it that a route here cannot be read without:
 *
 * - Escaping is expensive. Spiralling out of a circular orbit costs the whole of
 *   that orbit's speed — 7.7 km/s from low Earth orbit against the 3.2 an
 *   impulsive burn pays for the same escape. It is why Dawn was thrown onto an
 *   escape trajectory by a Delta II rather than spiralling off one itself.
 * - Arriving costs nothing at the top. The transfer ends matched to the target's
 *   orbit, so there is no hyperbola to capture from and no atmosphere worth
 *   entering: the arrival is the escape run backwards, another spiral.
 * - The phase still has to close. The crossing takes as long as it takes, so the
 *   trip leaves on the date that puts the target where the spiral ends, exactly
 *   as a chemical mission waits for its window.
 */

import { AU_KM } from '$lib/math/units';
import type { TravelBody } from './body';
import { CAPTURE_APOAPSIS_RADII, GM_SUN_KM3_S2, SEC_PER_DAY } from './constants';
import {
	arrivalCost,
	circularSpeed,
	parkingRadiusKm,
	type ArrivalMode,
	type EndOrbit
} from './maneuvers';
import type { Route, RouteLeg, RouteOptions } from './route';
import { elementsToState, type StateVector } from './state';
import { relativeState } from './system-transfer';
import { cross, dot, norm, normalize, type Vec3 } from './vec3';

const TWO_PI = Math.PI * 2;

/**
 * A drive, as the spiral model needs it: how hard it pushes to begin with, and
 * how fast that changes.
 *
 * The acceleration is the one at the start of the trip and rises all the way
 * through it as propellant leaves — which is not a detail, since these trips
 * spend most of their mass. Exhaust speed is what sets the rate, so the pair of
 * them is the whole time law.
 */
export interface LowThrustDrive {
	/** Acceleration at the start of the trip, m/s². */
	accelMs2: number;
	/** Exhaust speed, km/s. */
	veKms: number;
}

/**
 * Δv of an Edelbaum transfer between two circular orbits, km/s.
 *
 * The plane change is the expensive part and the reason this is not just the
 * difference of the two speeds: turning the velocity is paid for at the speed
 * the orbit is going, so the optimum spends most of it out at the slow end. The
 * quarter-turn inside the cosine is what that optimum works out to.
 */
export function edelbaumDvKms(v0Kms: number, v1Kms: number, planeChangeRad: number): number {
	const wedge = (Math.PI / 2) * planeChangeRad;
	const square = v0Kms * v0Kms + v1Kms * v1Kms - 2 * v0Kms * v1Kms * Math.cos(wedge);
	return Math.sqrt(Math.max(0, square));
}

/** How long the drive takes to deliver `dvKms`, days — Tsiolkovsky at constant
 *  thrust, so the ship gets lighter and the last kilometre per second is the
 *  quickest. */
export function spiralDays(dvKms: number, drive: LowThrustDrive): number {
	const accelKmS2 = drive.accelMs2 / 1000;
	if (!(dvKms > 0)) return 0;
	return ((drive.veKms / accelKmS2) * (1 - Math.exp(-dvKms / drive.veKms))) / SEC_PER_DAY;
}

/** The same drive once `dvKms` of it has been spent: lighter, so pushing harder. */
export function driveAfter(drive: LowThrustDrive, dvKms: number): LowThrustDrive {
	return { accelMs2: drive.accelMs2 * Math.exp(dvKms / drive.veKms), veKms: drive.veKms };
}

/** Samples along the transfer. Enough that the swept angle is good to a part in
 *  ten thousand, which is finer than the circular-orbit assumption under it. */
const TRANSFER_STEPS = 256;

/**
 * The heliocentric half of the trip: what it costs, how long it takes, and the
 * shape it takes it in.
 *
 * The samples are here because the drawn arc and the priced route have to be the
 * same spiral. They run from the start of the transfer to its end, and the angle
 * is what makes the trip land on the destination rather than merely on its
 * orbit — a spiral crosses two revolutions to get from Earth to Mars, and where
 * it comes out the far side is the whole of the phasing problem.
 */
export interface SpiralTransfer {
	dvKms: number;
	days: number;
	/** Angle swept about the centre, radians, in the direction of travel. */
	sweepRad: number;
	/** Orbit radius at each sample, km. */
	radiiKm: number[];
	/** Angle swept by each sample, radians. */
	sweptRad: number[];
	/** Days since the transfer began at each sample. */
	elapsedDays: number[];
}

/**
 * Build the transfer between two circular orbits under `drive`.
 *
 * The velocity follows a straight line in velocity space — the thrust holds one
 * direction relative to the orbit — so the speed at any point is the third side
 * of a triangle, and the radius is whatever circular orbit is going that fast.
 * The angle comes out of integrating the orbital rate against the Δv spent,
 * which is where the revolutions come from: a slow drive at Earth's distance
 * goes round twice on its way out.
 *
 * Returns null when the drive or either orbit is unusable, and for a transfer
 * that has to pass through zero speed — that is an escape, not a crossing, and
 * `spiralDays` prices it without needing a shape.
 */
export function spiralTransfer(
	v0Kms: number,
	v1Kms: number,
	planeChangeRad: number,
	mu: number,
	drive: LowThrustDrive,
	steps = TRANSFER_STEPS
): SpiralTransfer | null {
	const accelKmS2 = drive.accelMs2 / 1000;
	if (!(accelKmS2 > 0) || !(drive.veKms > 0)) return null;
	if (!(v0Kms > 0) || !(v1Kms > 0) || !(mu > 0)) return null;

	const dvKms = edelbaumDvKms(v0Kms, v1Kms, planeChangeRad);
	if (!isFinite(dvKms)) return null;

	// Two orbits that are already the same one: nothing to fly, which is a real
	// answer for a pair of co-orbital bodies rather than a failure.
	if (dvKms === 0) {
		const r = mu / (v0Kms * v0Kms);
		return {
			dvKms: 0,
			days: 0,
			sweepRad: 0,
			radiiKm: [r, r],
			sweptRad: [0, 0],
			elapsedDays: [0, 0]
		};
	}

	// Where the thrust points, as the angle between it and the velocity it starts
	// on — read off the same triangle that gave the Δv.
	const cosYaw = (v0Kms * v0Kms + dvKms * dvKms - v1Kms * v1Kms) / (2 * v0Kms * dvKms);

	const radiiKm: number[] = [];
	const sweptRad: number[] = [];
	const elapsedDays: number[] = [];
	const step = dvKms / steps;
	let swept = 0;
	let lastRate = 0;

	for (let i = 0; i <= steps; i++) {
		const spent = step * i;
		const speed = Math.sqrt(
			Math.max(0, v0Kms * v0Kms + spent * spent - 2 * v0Kms * spent * cosYaw)
		);
		if (!(speed > 0)) return null;
		const radius = mu / (speed * speed);
		// Angle per unit Δv: how fast the orbit goes round, over how fast the drive
		// is spending — and the drive spends faster as it lightens.
		const rate = (speed * speed * speed) / (mu * accelKmS2 * Math.exp(spent / drive.veKms));
		if (i > 0) swept += ((rate + lastRate) / 2) * step;
		lastRate = rate;

		radiiKm.push(radius);
		sweptRad.push(swept);
		elapsedDays.push(spiralDays(spent, drive));
	}

	const days = elapsedDays[elapsedDays.length - 1];
	if (!isFinite(days) || !isFinite(swept)) return null;
	return { dvKms, days, sweepRad: swept, radiiKm, sweptRad, elapsedDays };
}

/**
 * The three burns a spiral trip is made of, before any of them is timed.
 *
 * Which of them exist depends on what the trip goes round: an interplanetary
 * crossing climbs out of one well and down into another, while a trip to a body's
 * own moon never leaves the primary and so has only the climb.
 */
interface SpiralPlan {
	/** μ the transfer itself goes round, km³/s². */
	mu: number;
	/** Circular speeds the transfer runs between, km/s. */
	v0Kms: number;
	v1Kms: number;
	planeChangeRad: number;
	/** Δv to spiral out of the body the trip leaves, km/s. Zero when it stays
	 *  bound to the one it started at. */
	escapeKms: number;
	/** Δv to spiral down at the far end, km/s. */
	captureKms: number;
	/** Whether the arrival has to be phased. False when one end of the trip is a
	 *  parking orbit, whose place in its orbit is ours to choose. */
	phased: boolean;
}

/**
 * Radius the arrival spiral stops at, km — the orbit that was asked for.
 *
 * A spiral is quasi-circular the whole way, so an elliptical orbit is met at its
 * apoapsis: that is where the climb stops and the shape is someone else's
 * problem.
 */
function arrivalRadiusKm(body: TravelBody, mode: ArrivalMode, orbit?: EndOrbit): number {
	if (orbit) return orbit.rApoKm;
	return mode === 'capture' ? CAPTURE_APOAPSIS_RADII * body.radiusKm : parkingRadiusKm(body);
}

/** Angle between the planes of two orbits, radians. Taken from the states rather
 *  than the elements so that a satellite referenced to its planet's equator and a
 *  planet referenced to the ecliptic can still be compared. */
function planeChangeRad(a: StateVector, b: StateVector): number {
	const ha = cross(a.r, a.v);
	const hb = cross(b.r, b.v);
	const na = norm(ha);
	const nb = norm(hb);
	if (!(na > 0) || !(nb > 0)) return 0;
	return Math.acos(Math.max(-1, Math.min(1, dot(ha, hb) / (na * nb))));
}

function circularRadiusKm(body: TravelBody): number {
	return body.elements.a * AU_KM;
}

/** Weight per kilogram at the surface, m/s² — what a landing has to push against. */
function surfaceGravityMs2(body: TravelBody): number {
	return (body.mu / (body.radiusKm * body.radiusKm)) * 1000;
}

function spiralPlan(
	departure: TravelBody,
	target: TravelBody,
	jd: number,
	options: Required<Pick<RouteOptions, 'centralMu' | 'arrivalMode'>> &
		Pick<RouteOptions, 'systemPrimary' | 'departureOrbit' | 'targetOrbit'>
): SpiralPlan | null {
	const { centralMu, arrivalMode, systemPrimary, departureOrbit, targetOrbit } = options;

	// A trip to a body's own moon, or back: the transfer goes round the primary
	// and never leaves it, so the climb out of the parking orbit *is* the
	// crossing. Its phase is ours to pick, which is what spares these the wait.
	if (systemPrimary) {
		const outbound = systemPrimary === 'departure';
		const primary = outbound ? departure : target;
		const satellite = outbound ? target : departure;
		const state = relativeState(satellite, primary, jd);
		if (!state) return null;
		const rSat = norm(state.r);
		const rPark = (outbound ? departureOrbit : targetOrbit)?.rPeriKm ?? parkingRadiusKm(primary);
		if (!(rSat > 0) || !(rPark > 0) || !(primary.mu > 0)) return null;

		const vPark = circularSpeed(primary.mu, rPark);
		const vSat = circularSpeed(primary.mu, rSat);
		return {
			mu: primary.mu,
			v0Kms: outbound ? vPark : vSat,
			v1Kms: outbound ? vSat : vPark,
			planeChangeRad: 0,
			// Leaving a satellite means climbing out of it first; leaving a parking
			// orbit about the primary means the transfer has already started.
			escapeKms: outbound
				? 0
				: circularSpeed(satellite.mu, departureOrbit?.rPeriKm ?? parkingRadiusKm(satellite)),
			// Arriving at the primary, the spiral ends in the orbit that was asked
			// for and there is nothing further to pay.
			captureKms:
				outbound && arrivalMode !== 'flyby'
					? circularSpeed(satellite.mu, arrivalRadiusKm(satellite, arrivalMode, targetOrbit))
					: 0,
			phased: false
		};
	}

	const from = elementsToState(departure.elements, jd, centralMu);
	const to = elementsToState(target.elements, jd, centralMu);
	if (!from || !to) return null;

	const r0 = circularRadiusKm(departure);
	const r1 = circularRadiusKm(target);
	// An orbit with no semi-major axis is not one a spiral can be matched to: an
	// escaping probe or an interstellar comet is a different problem entirely.
	if (!(r0 > 0) || !(r1 > 0) || !isFinite(r0) || !isFinite(r1)) return null;

	return {
		mu: centralMu,
		v0Kms: circularSpeed(centralMu, r0),
		v1Kms: circularSpeed(centralMu, r1),
		planeChangeRad: planeChangeRad(from, to),
		escapeKms: circularSpeed(departure.mu, departureOrbit?.rPeriKm ?? parkingRadiusKm(departure)),
		// A flyby has nothing to slow down for. The crossing is still charged in
		// full: the craft has to reach the target's orbit to cross it, and the
		// cheaper arc that merely passes through is not one this model draws.
		captureKms:
			arrivalMode === 'flyby'
				? 0
				: circularSpeed(target.mu, arrivalRadiusKm(target, arrivalMode, targetOrbit)),
		phased: true
	};
}

/** Where the transfer measures its angles from: the plane the departure orbits
 *  in, with the departure's own direction as the zero. */
interface PlaneBasis {
	/** Zero of the angle. */
	u: Vec3;
	/** A quarter turn ahead of it, in the direction of travel. */
	w: Vec3;
}

function planeBasis(state: StateVector): PlaneBasis | null {
	const u = normalize(state.r);
	const h = cross(state.r, state.v);
	if (!(norm(u) > 0) || !(norm(h) > 0)) return null;
	const w = normalize(cross(h, state.r));
	if (!(norm(w) > 0)) return null;
	return { u, w };
}

/** Angle of `r` about the basis, radians in (−π, π]. */
function angleIn(basis: PlaneBasis, r: Vec3): number {
	return Math.atan2(dot(r, basis.w), dot(r, basis.u));
}

function wrapPi(angle: number): number {
	let x = angle % TWO_PI;
	if (x > Math.PI) x -= TWO_PI;
	if (x <= -Math.PI) x += TWO_PI;
	return x;
}

/**
 * The longest wait this will offer, days.
 *
 * Phasing repeats on the synodic period of the two orbits, so two bodies with
 * nearly the same year can be out of position for a human lifetime. Past this
 * there is no route worth showing: the answer stops being "leave in 2043" and
 * starts being "not with this drive".
 */
const MAX_PHASE_WAIT_DAYS = 50 * 365.25;
/** Samples per synodic period while looking for the alignment, then bisection. */
const PHASE_SCAN_STEPS = 360;
const PHASE_BISECTION_STEPS = 40;

/**
 * The first date on or after `earliestJd` whose spiral ends where the target is.
 *
 * The transfer's shape is fixed by the two orbits and the drive, so its swept
 * angle is a constant and the only free variable is when to start. That makes
 * this the same search a Hohmann window is: one alignment per synodic period,
 * found by watching the angle between where the spiral comes out and where the
 * destination has got to.
 */
function phasedDeparture(
	departure: TravelBody,
	target: TravelBody,
	earliestJd: number,
	escapeDays: number,
	transfer: SpiralTransfer,
	centralMu: number
): number | null {
	const reference = elementsToState(departure.elements, earliestJd + escapeDays, centralMu);
	if (!reference) return null;
	const basis = planeBasis(reference);
	if (!basis) return null;

	const cruiseDays = transfer.days;
	const miss = (departJd: number): number | null => {
		const from = elementsToState(departure.elements, departJd + escapeDays, centralMu);
		const to = elementsToState(target.elements, departJd + escapeDays + cruiseDays, centralMu);
		if (!from || !to) return null;
		return wrapPi(angleIn(basis, from.r) + transfer.sweepRad - angleIn(basis, to.r));
	};

	const nDep = departure.elements.n;
	const nTar = target.elements.n;
	if (!isFinite(nDep) || !isFinite(nTar)) return null;
	const synodicDays = Math.abs(nDep - nTar) > 0 ? 360 / Math.abs(nDep - nTar) : Infinity;
	if (!(synodicDays <= MAX_PHASE_WAIT_DAYS)) {
		console.debug(
			`[travel] no low-thrust window for ${departure.id} → ${target.id}: ` +
				`the phase repeats every ${(synodicDays / 365.25).toFixed(0)} years.`
		);
		return null;
	}

	const step = synodicDays / PHASE_SCAN_STEPS;
	let prevJd = earliestJd;
	let prev = miss(prevJd);
	if (prev === null) return null;
	if (prev === 0) return earliestJd;

	for (let i = 1; i <= PHASE_SCAN_STEPS + 1; i++) {
		const jd = earliestJd + step * i;
		const value = miss(jd);
		if (value === null) return null;
		// A jump of more than half a turn is the angle wrapping rather than the
		// alignment arriving.
		if (prev <= 0 !== value <= 0 && Math.abs(value - prev) < Math.PI) {
			let lo = prevJd;
			let hi = jd;
			const negative = prev <= 0;
			for (let k = 0; k < PHASE_BISECTION_STEPS; k++) {
				const mid = (lo + hi) / 2;
				const at = miss(mid);
				if (at === null) break;
				if (at <= 0 === negative) lo = mid;
				else hi = mid;
			}
			return (lo + hi) / 2;
		}
		prevJd = jd;
		prev = value;
	}
	return null;
}

/**
 * Build the spiral trip leaving on or after `earliestJd`.
 *
 * Returns null when the drive cannot fly this trip at all — off a surface, which
 * nothing with a thrust-to-weight of a thousandth leaves; between orbits too
 * alike for the phase to ever close; or where either end has no orbit to be
 * matched to.
 */
export function buildLowThrustRoute(
	departure: TravelBody,
	target: TravelBody,
	earliestJd: number,
	drive: LowThrustDrive,
	options: RouteOptions = {}
): Route | null {
	const {
		departureMode = 'surface',
		arrivalMode = 'capture',
		aero = 'none',
		centralMu = GM_SUN_KM3_S2,
		systemPrimary
	} = options;

	// Nothing that pushes at a thousandth of a gravity lifts itself off anything.
	// The trip starting on the ground is a statement about the trip, so this is a
	// refusal to offer the route rather than a route that is out of reach.
	if (departureMode === 'surface') return null;
	// The same the other way up. Every other burn on a spiral trip is spent across
	// gravity and can take as long as it likes; a touchdown is spent against it,
	// and a drive that cannot hold the craft up cannot set it down.
	if (arrivalMode === 'landing' && drive.accelMs2 < surfaceGravityMs2(target)) return null;

	const shape = spiralPlan(departure, target, earliestJd, {
		centralMu,
		arrivalMode,
		systemPrimary,
		departureOrbit: options.departureOrbit,
		targetOrbit: options.targetOrbit
	});
	if (!shape) return null;

	const escapeDays = spiralDays(shape.escapeKms, drive);
	const cruiseDrive = driveAfter(drive, shape.escapeKms);
	const transfer = spiralTransfer(
		shape.v0Kms,
		shape.v1Kms,
		shape.planeChangeRad,
		shape.mu,
		cruiseDrive
	);
	if (!transfer) return null;
	const captureDrive = driveAfter(cruiseDrive, transfer.dvKms);
	const captureDays = spiralDays(shape.captureKms, captureDrive);

	const departJd = shape.phased
		? phasedDeparture(departure, target, earliestJd, escapeDays, transfer, centralMu)
		: earliestJd;
	if (departJd === null) return null;

	// The arrival is where the crossing ends. What happens after it — the spiral
	// down, and the landing if one was asked for — is time spent at the
	// destination, the way an aerobraking campaign is.
	const tofDays = escapeDays + transfer.days;
	const arriveJd = departJd + tofDays;

	const legs: RouteLeg[] = [];
	if (shape.escapeKms > 0) {
		legs.push({ kind: 'spiral-out', dvKms: shape.escapeKms, days: escapeDays });
	}
	legs.push({ kind: 'powered-cruise', dvKms: transfer.dvKms, days: transfer.days });
	if (shape.captureKms > 0) {
		legs.push({ kind: 'spiral-in', dvKms: shape.captureKms, days: captureDays });
	}
	// Only the descent is taken from the shared arrival model: a spiral arrives
	// with no excess speed to capture from and never meets the atmosphere, so the
	// rest of what that model prices did not happen. The landing itself is the one
	// burn here an ion drive could not fly — `checkFeasibility` is where that is
	// said, since it is a fact about the craft rather than about the route.
	if (arrivalMode === 'landing') {
		const descentKms = arrivalCost(target, 0, 'landing', aero).descentKms;
		if (descentKms > 0) legs.push({ kind: 'descent', dvKms: descentKms, days: 0 });
	}

	const totalDvKms = legs.reduce((sum, leg) => sum + leg.dvKms, 0);
	if (!isFinite(totalDvKms) || !isFinite(arriveJd)) return null;

	return {
		departureId: departure.id,
		targetId: target.id,
		departJd,
		arriveJd,
		tofDays,
		legs,
		totalDvKms,
		// Nothing is thrown, so nothing was launched: every kilometre per second
		// here is the craft's own, whatever it started from.
		inSpaceDvKms: totalDvKms,
		c3Km2S2: 0,
		vInfDepKms: 0,
		vInfArrKms: 0,
		departureMode,
		arrivalMode,
		departureOrbit: options.departureOrbit,
		targetOrbit: options.targetOrbit,
		aero,
		lowThrust: { accelMs2: drive.accelMs2, veKms: drive.veKms }
	};
}

/**
 * The crossing of a spiral route, rebuilt.
 *
 * Same inputs, same builder, so the arc the map draws is the one the ladder
 * charged for — nothing has to be carried across from the solve or kept in step
 * by hand.
 */
export function rebuildSpiral(
	departure: TravelBody,
	target: TravelBody,
	route: Route,
	options: RouteOptions = {},
	steps = TRANSFER_STEPS
): { transfer: SpiralTransfer; startJd: number } | null {
	const drive = route.lowThrust;
	if (!drive) return null;
	const { arrivalMode = 'capture', centralMu = GM_SUN_KM3_S2, systemPrimary } = options;

	const shape = spiralPlan(departure, target, route.departJd, {
		centralMu,
		arrivalMode,
		systemPrimary,
		departureOrbit: options.departureOrbit,
		targetOrbit: options.targetOrbit
	});
	if (!shape) return null;

	const transfer = spiralTransfer(
		shape.v0Kms,
		shape.v1Kms,
		shape.planeChangeRad,
		shape.mu,
		driveAfter(drive, shape.escapeKms),
		steps
	);
	if (!transfer) return null;
	return { transfer, startJd: route.departJd + spiralDays(shape.escapeKms, drive) };
}
