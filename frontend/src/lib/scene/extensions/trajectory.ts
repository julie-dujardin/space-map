/**
 * Where a host's own object is, at any date. Each of these builds an anchor —
 * a body and an offset from it in kilometres — so a trajectory carries an
 * object, a marker, a drawing or the camera alike, and everything placed by
 * one keeps up with the body it is measured from.
 *
 * The offsets are on ecliptic J2000 axes, the frame the export publishes
 * positions in. A trajectory that says nothing at a date returns null there
 * and whatever it carries is not drawn: a state list ends, a decayed satellite
 * stops propagating.
 */

import { SUN_ID, EARTH_ID } from '$lib/constants';
import { AU_KM, EARTH_OBLIQUITY_DEG } from '$lib/math/units';
import { elementsToState } from '$lib/math/travel/state';
import { sgp4PositionTEME } from '$lib/math/orbit/sgp4';
import type { OrbitalElements } from '$lib/types/objects';
import { twoline2satrec, SatRecError } from 'satellite.js';
import type { Anchor, InertialAnchor, OffsetKm } from './anchor';

const RAD = Math.PI / 180;
const COS_EPS = Math.cos(EARTH_OBLIQUITY_DEG * RAD);
const SIN_EPS = Math.sin(EARTH_OBLIQUITY_DEG * RAD);

/** One state on a sampled trajectory: a date, and where the object was on it. */
export interface TrajectorySample {
	/** Julian date. */
	jd: number;
	/** Kilometres from the reference body on ecliptic J2000 axes. */
	km: OffsetKm;
}

export interface SamplesOptions {
	/** What the states are measured from; the Sun when left out. */
	body?: string;
	/** Two or more states. They are sorted by date, so they may be given in any
	 *  order; fewer than two places nothing. */
	samples: readonly TrajectorySample[];
}

export interface ElementsOptions {
	/** What the orbit is round; the Sun when left out. */
	body?: string;
	/** The export's own elements: `a` in astronomical units, angles in degrees,
	 *  `n` in degrees a day, `epoch` a Julian date. Set `equatorial` when the
	 *  angles are referenced to Earth's equator rather than the ecliptic. */
	elements: OrbitalElements;
}

/** A place that does not move: on a body's surface, or at a fixed offset from
 *  its centre. It is already an anchor — this names it beside the trajectories
 *  that do move. */
export function fixed(place: Anchor): Anchor {
	return place;
}

/**
 * A list of states the map reads between. Between two states the path is a
 * cubic through both of them, tangent to the slope each state's neighbours
 * imply — the smooth curve a coasting object actually follows, where a
 * straight line between states would cut every corner of an orbit. Outside the
 * range the states cover the object is not drawn: a list that has run out is
 * not evidence of where anything is.
 */
export function samples(options: SamplesOptions): InertialAnchor {
	const states = [...options.samples].sort((a, b) => a.jd - b.jd);
	return {
		body: options.body ?? SUN_ID,
		offsetKm: (jd) => interpolateSamples(states, jd)
	};
}

/**
 * A Keplerian orbit, propagated from its epoch by the mean motion the elements
 * carry. Defined at every date, so an object on one is always drawn.
 */
export function elements(options: ElementsOptions): InertialAnchor {
	return {
		body: options.body ?? SUN_ID,
		offsetKm: (jd) => elementsToState(options.elements, jd)?.r ?? null
	};
}

/**
 * Two lines of a NORAD element set, propagated with SGP4 — the model the
 * elements are fitted for, so a satellite's nodal drift and drag are in the
 * position rather than a mean ellipse. The orbit is round Earth, since that is
 * what a TLE describes.
 *
 * Accuracy falls away from the element set's epoch, a few days either side
 * being the usual working range. A set SGP4 will not take, and a date it
 * cannot be propagated to — a decayed satellite, most often — leave the object
 * undrawn.
 */
export function tle(line1: string, line2: string): InertialAnchor {
	const satrec = twoline2satrec(line1, line2);
	if (satrec.error !== SatRecError.None) {
		console.warn(`spacemap: SGP4 will not take this element set (error=${satrec.error})`);
	}
	return {
		body: EARTH_ID,
		offsetKm: (jd) => {
			if (satrec.error !== SatRecError.None) return null;
			const teme = sgp4PositionTEME(satrec, jd);
			return teme && temeToEcliptic(teme[0], teme[1], teme[2]);
		}
	};
}

/** TEME kilometres to ecliptic J2000 kilometres: one turn about the shared
 *  vernal-equinox axis by the obliquity. */
function temeToEcliptic(x: number, y: number, z: number): OffsetKm {
	return [x, y * COS_EPS + z * SIN_EPS, -y * SIN_EPS + z * COS_EPS];
}

/**
 * Position at `jd` on the cubic through the states either side of it, with
 * each state's tangent taken from its two neighbours over their own spacing —
 * so states given at uneven intervals are read as they were meant. Null
 * outside the range, and for a list too short to describe a path.
 */
export function interpolateSamples(
	states: readonly TrajectorySample[],
	jd: number
): OffsetKm | null {
	const n = states.length;
	if (n < 2 || jd < states[0].jd || jd > states[n - 1].jd) return null;

	// First state at or after jd, so the interval is [i - 1, i].
	let lo = 0;
	let hi = n - 1;
	while (lo < hi) {
		const mid = (lo + hi) >> 1;
		if (states[mid].jd < jd) lo = mid + 1;
		else hi = mid;
	}
	const i = Math.max(lo, 1);
	const before = states[i - 1];
	const after = states[i];
	const dt = after.jd - before.jd;
	// Two states on the same date: the later one wins rather than dividing by zero.
	if (dt <= 0) return after.km;

	const s = (jd - before.jd) / dt;
	const s2 = s * s;
	const s3 = s2 * s;
	const h00 = 2 * s3 - 3 * s2 + 1;
	const h10 = s3 - 2 * s2 + s;
	const h01 = -2 * s3 + 3 * s2;
	const h11 = s3 - s2;

	const out: [number, number, number] = [0, 0, 0];
	for (let axis = 0; axis < 3; axis++) {
		const p0 = before.km[axis];
		const p1 = after.km[axis];
		const m0 = tangent(states, i - 1, axis);
		const m1 = tangent(states, i, axis);
		out[axis] = h00 * p0 + h10 * dt * m0 + h01 * p1 + h11 * dt * m1;
	}
	return out;
}

/** Slope at state `i` on one axis: the difference across its neighbours, or
 *  the one-sided difference at an end of the list. */
function tangent(states: readonly TrajectorySample[], i: number, axis: number): number {
	const previous = states[i - 1] ?? states[i];
	const next = states[i + 1] ?? states[i];
	const span = next.jd - previous.jd;
	if (span <= 0) return 0;
	return (next.km[axis] - previous.km[axis]) / span;
}

/** Kilometres as astronomical units. Orbital elements are quoted with their
 *  semi-major axis in AU wherever the map reads them, and that is the one
 *  distance on the public surface which is not in kilometres. */
export function kmToAu(km: number): number {
	return km / AU_KM;
}
