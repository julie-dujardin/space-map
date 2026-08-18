/**
 * The slice of a body the trajectory model needs. Deliberately narrow so it can
 * be filled from an export detail record, a binary elements row, or a fixture,
 * and so the maths never reaches back into the fetch layer.
 */

import type { OrbitalElements } from '$lib/types/objects';
import { AU_KM } from '$lib/math/units';
import { ASSUMED_DENSITY_KG_M3, G_KM3_KG_S2, SEC_PER_DAY } from './constants';
import { dot, norm, type Vec3 } from './vec3';

/**
 * Where a body really is, for the ones no conic about their primary describes.
 * An osculating fit is only a local truth: Webb's fit about Earth reads as a
 * 126-day ellipse swinging 0.6–1.5 million km, though Webb never leaves L2. A
 * trip priced against it would climb to a distance the body was never at.
 *
 * So these are measured positions instead — ascending dates, measured from
 * `centerId`, ecliptic J2000, km and km/s. Plain arrays, since a solve runs in
 * a worker and takes its bodies by copy.
 */
export interface EphemerisSamples {
	/** The body the positions are measured from. */
	centerId: string;
	/** Sample dates, ascending. */
	jds: number[];
	r: Vec3[];
	v: Vec3[];
}

export interface TravelBody {
	/** Prefixed object id, e.g. "naif-499". */
	id: string;
	/** Gravitational parameter, km³/s². */
	mu: number;
	/** True when `mu` came from assumed density rather than a measurement. */
	muEstimated: boolean;
	/** Mean radius, km. */
	radiusKm: number;
	/** Elements placing the body about its primary. */
	elements: OrbitalElements;
	/**
	 * Surface pressure in bar. Absent means no reading at a surface — either
	 * airless, or no surface to read at. What ascent and landing are priced
	 * against.
	 */
	surfacePressureBar?: number;
	/**
	 * True when any envelope has been detected, down to Mercury's exosphere.
	 * Says nothing about flyability — that's `aeroPressurePa`'s job — but tells
	 * a gas giant apart from an airless body when neither has surface pressure.
	 */
	hasAtmosphere?: boolean;
	/**
	 * Pressure of the envelope at the level `radiusKm` names — surface, or 1 bar
	 * on a giant — in Pa. Only set for a measured envelope a pass could fly
	 * through, so upper limits and stellar photospheres never carry one. What
	 * aero eligibility and pass depth are priced against.
	 */
	aeroPressurePa?: number;
	/** Density scale height of that envelope, km — sets how deep the pass sits. */
	aeroScaleHeightKm?: number;
	/** Altitude the rendered atmosphere shell tops out at, km — where a drawn
	 *  line starts compositing under the glow instead of over it. */
	aeroShellTopKm?: number;
	/** Rotation rate about its own axis, rad/s, sign dropped — what the ground at
	 *  the equator is already moving at, and so what an ascent is spared. */
	spinRadPerSec?: number;
	/**
	 * North pole as a unit vector in ecliptic J2000 axes — the frame the states
	 * are in. Sets how far a departure or approach lies out of the body's
	 * equator, the lowest a reaching plane can be. From the IAU pole; absent for
	 * a body with no shipped orientation.
	 */
	poleEcliptic?: Vec3;
	/** Primary this body orbits; absent for heliocentric bodies. */
	parentId?: string;
	/** Measured positions about the primary, where the elements cannot be
	 *  trusted over a trip's length. See {@link EphemerisSamples}. */
	samples?: EphemerisSamples;
	/**
	 * True when `elements` place a centre the body is nowhere near — the Moon
	 * flown as "a Moon-sized body on Earth's orbit". Fine for a crossing;
	 * anything drawn *at* this body is wrong, since the elements give the
	 * ancestor's position. Not simply "someone else's elements": a planet
	 * borrows its own system barycentre, for Earth a point under the surface.
	 */
	borrowedElements?: boolean;
}

/**
 * GM from a radius and an assumed bulk density — fallback for the small bodies
 * in most of the catalogue, where no mass has been measured. Capture and
 * landing costs are metres per second either way at these scales, so the error
 * never moves a route decision; callers surface it as an estimate.
 */
export function estimateMu(radiusKm: number, densityKgM3 = ASSUMED_DENSITY_KG_M3): number {
	const volumeKm3 = (4 / 3) * Math.PI * radiusKm ** 3;
	return G_KM3_KG_S2 * densityKgM3 * 1e9 * volumeKm3;
}

/**
 * μ of whatever a body goes round, km³/s², from Kepler's third law. A
 * satellite's own period and distance name the mass at the focus, so a pair of
 * moons can price a transfer about their planet without looking it up. Agrees
 * with a measured GM to about the seven digits the packed mean motion carries,
 * since that's what it was fitted against.
 */
export function muFromElements(el: OrbitalElements): number {
	const nRadPerSec = (el.n * (Math.PI / 180)) / SEC_PER_DAY;
	const aKm = el.a * AU_KM;
	return nRadPerSec * nRadPerSec * aKm ** 3;
}

/** Surface escape velocity, km/s. */
export function escapeSpeed(body: TravelBody): number {
	return Math.sqrt((2 * body.mu) / body.radiusKm);
}

/**
 * How far a direction lies out of the body's equator, degrees, unsigned. An
 * orbit can only contain a direction if inclined at least this much, so it's
 * the floor under a departure or approach plane. Undefined when the body ships
 * no pole: the plane is then bounded only by where the trip touches ground.
 */
export function equatorialTiltDeg(body: TravelBody, direction: Vec3): number | undefined {
	const pole = body.poleEcliptic;
	if (!pole) return undefined;
	// Both lengths divided out: the arcsine is steepest here, so a pole a
	// rounding short of unit would read as whole degrees of tilt.
	const n = norm(direction) * norm(pole);
	if (!(n > 0)) return undefined;
	const sinDec = Math.min(1, Math.max(-1, dot(direction, pole) / n));
	return Math.abs(Math.asin(sinDec)) * (180 / Math.PI);
}

/**
 * Radius of the sphere of influence, km — where the body's pull overtakes its
 * primary's. Bounds where a patched-conic leg is meaningful.
 */
export function sphereOfInfluenceKm(body: TravelBody, primaryMu: number, aKm: number): number {
	if (!(primaryMu > 0) || !(aKm > 0)) return Infinity;
	return aKm * Math.pow(body.mu / primaryMu, 0.4);
}
