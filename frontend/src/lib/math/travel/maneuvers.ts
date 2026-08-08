/**
 * Δv for the manoeuvres that bracket a transfer: getting off one body and
 * arriving at another.
 *
 * These are patched-conic estimates with published loss factors, not
 * trajectory-optimiser output. They are good to a few percent for the burns
 * that dominate a mission budget, which is what a comparison between
 * destinations needs. Every approximation is named in the constants module.
 */

import type { TravelBody } from './body';
import {
	AEROCAPTURE_MIN_PRESSURE_BAR,
	AEROCAPTURE_SAVING_FRACTION,
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

/** True when the atmosphere is thick enough to brake or land against. */
export function hasUsableAtmosphere(body: TravelBody): boolean {
	return (body.surfacePressureBar ?? 0) >= AEROCAPTURE_MIN_PRESSURE_BAR;
}

/**
 * Δv from the surface to the parking orbit, km/s.
 *
 * Circular velocity plus gravity/steering losses scaled by surface gravity,
 * plus a drag term for bodies with an atmosphere. The drag term is capped
 * because it is linear in pressure and Venus would otherwise dominate the
 * result on a coefficient that was only ever fitted near 1 bar.
 */
export function ascentDv(body: TravelBody): number {
	const vCirc = circularSpeed(body.mu, parkingRadiusKm(body));
	const gravityLoss = ASCENT_GRAVITY_LOSS_FRACTION * circularSpeed(body.mu, body.radiusKm);
	const drag = Math.min(
		ASCENT_DRAG_LOSS_CAP_KMS,
		ASCENT_DRAG_LOSS_KMS_PER_BAR * (body.surfacePressureBar ?? 0)
	);
	return vCirc + gravityLoss + drag;
}

/**
 * Δv to leave a circular parking orbit on a hyperbola with excess speed
 * `vInfKms`. The Oberth effect is why this is so much less than `vInf` itself.
 */
export function injectionDv(mu: number, rParkKm: number, vInfKms: number): number {
	return Math.sqrt(vInfKms * vInfKms + (2 * mu) / rParkKm) - circularSpeed(mu, rParkKm);
}

/**
 * Δv to drop from an arrival hyperbola into a bound orbit with periapsis
 * `rPeriKm` and apoapsis `rApoKm`. Passing `rApoKm = rPeriKm` gives circular
 * capture; a loose ellipse is far cheaper and is what real orbiters do first.
 */
export function captureDv(mu: number, rPeriKm: number, rApoKm: number, vInfKms: number): number {
	const vHyp = Math.sqrt(vInfKms * vInfKms + (2 * mu) / rPeriKm);
	const vBound = Math.sqrt((2 * mu) / rPeriKm - (2 * mu) / (rPeriKm + rApoKm));
	return Math.max(0, vHyp - vBound);
}

export type ArrivalMode = 'flyby' | 'capture' | 'low-orbit' | 'landing';

export interface ArrivalCost {
	/** Δv to reach the bound orbit, km/s. Zero for a flyby. */
	captureKms: number;
	/** Δv from that orbit down to the surface, km/s. Zero unless landing. */
	descentKms: number;
	/** True when an atmosphere absorbed part of the arrival. */
	aerobraked: boolean;
}

/**
 * Δv to arrive at `body` in the requested way, given the hyperbolic excess
 * speed the transfer delivers.
 *
 * An atmosphere discounts capture, and replaces most of a powered descent with
 * a heat shield and parachutes — which is why Titan is cheap to land on and
 * Mercury is not.
 */
export function arrivalCost(body: TravelBody, vInfKms: number, mode: ArrivalMode): ArrivalCost {
	if (mode === 'flyby') return { captureKms: 0, descentKms: 0, aerobraked: false };

	const rPeri = parkingRadiusKm(body);
	const aero = hasUsableAtmosphere(body);
	const rApo = mode === 'capture' ? CAPTURE_APOAPSIS_RADII * body.radiusKm : rPeri;

	let capture = captureDv(body.mu, rPeri, rApo, vInfKms);
	if (aero) capture *= 1 - AEROCAPTURE_SAVING_FRACTION;

	if (mode !== 'landing') return { captureKms: capture, descentKms: 0, aerobraked: aero };

	// Landing on an airless body is ascent run backwards; with an atmosphere the
	// entry system does the work and only touchdown is propulsive.
	const descent = aero
		? POWERED_TOUCHDOWN_KMS
		: circularSpeed(body.mu, rPeri) +
			ASCENT_GRAVITY_LOSS_FRACTION * circularSpeed(body.mu, body.radiusKm);

	return { captureKms: capture, descentKms: descent, aerobraked: aero };
}

export type DepartureMode = 'surface' | 'orbit';

/**
 * Δv to get from `body` onto a transfer needing excess speed `vInfKms`,
 * starting either from the ground or from an existing parking orbit.
 */
export function departureCost(
	body: TravelBody,
	vInfKms: number,
	mode: DepartureMode
): { ascentKms: number; injectionKms: number } {
	return {
		ascentKms: mode === 'surface' ? ascentDv(body) : 0,
		injectionKms: injectionDv(body.mu, parkingRadiusKm(body), vInfKms)
	};
}

/** Characteristic energy, km²/s² — the figure launch vehicles are rated against. */
export function characteristicEnergy(vInfKms: number): number {
	return vInfKms * vInfKms;
}
