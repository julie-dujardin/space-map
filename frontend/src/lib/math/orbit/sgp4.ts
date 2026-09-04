/**
 * SGP4 propagation for Earth satellites via satellite.js — replaces the plain
 * Kepler mean-motion step for TLE-sourced objects so the position includes
 * J2 nodal/apsidal drift, atmospheric drag (B*), and short-period TEME oscillations.
 */

import { json2satrec, sgp4, type SatRec, SatRecError, type OMMJsonObject } from 'satellite.js';
import { AU_KM, AU_SCALE, EARTH_OBLIQUITY_DEG } from '$lib/math/units';

const DEG2RAD = Math.PI / 180;
const COS_EPS = Math.cos(EARTH_OBLIQUITY_DEG * DEG2RAD);
const SIN_EPS = Math.sin(EARTH_OBLIQUITY_DEG * DEG2RAD);
/** 1970-01-01 00:00:00 UTC as a Julian Date. */
const JD_UNIX_EPOCH = 2440587.5;

/** Convert a Julian Date to an ISO-8601 UTC string — the format json2satrec expects for EPOCH. */
export function jdToIso(jd: number): string {
	return new Date((jd - JD_UNIX_EPOCH) * 86400000).toISOString();
}

/**
 * Raw OMM-ish inputs as they appear in the binary export. Units match the
 * CelesTrak gp-active.csv columns — json2satrec expects these unconverted.
 */
export interface SGP4Inputs {
	noradCatId: number;
	epochJd: number;
	meanMotion: number; // rev/day
	eccentricity: number;
	inclination: number; // deg
	raOfAscNode: number; // deg
	argOfPericenter: number; // deg
	meanAnomaly: number; // deg
	bstar: number; // 1 / Earth radius
	meanMotionDot: number; // rev/day²
	meanMotionDdot: number; // rev/day³
	elementSetNo: number;
	revAtEpoch: number;
}

/**
 * Build an SGP4 satrec from raw OMM fields. Returns null and logs when the
 * satellite failed to initialize (out-of-range ecc, etc.) — this follows the
 * "log when data is filtered out" rule.
 */
export function buildSatrec(inputs: SGP4Inputs, name?: string): SatRec | null {
	const omm: OMMJsonObject = {
		OBJECT_NAME: name ?? String(inputs.noradCatId),
		OBJECT_ID: String(inputs.noradCatId),
		EPOCH: jdToIso(inputs.epochJd),
		MEAN_MOTION: inputs.meanMotion,
		ECCENTRICITY: inputs.eccentricity,
		INCLINATION: inputs.inclination,
		RA_OF_ASC_NODE: inputs.raOfAscNode,
		ARG_OF_PERICENTER: inputs.argOfPericenter,
		MEAN_ANOMALY: inputs.meanAnomaly,
		EPHEMERIS_TYPE: 0,
		CLASSIFICATION_TYPE: 'U',
		NORAD_CAT_ID: inputs.noradCatId,
		ELEMENT_SET_NO: inputs.elementSetNo,
		REV_AT_EPOCH: inputs.revAtEpoch,
		BSTAR: inputs.bstar,
		MEAN_MOTION_DOT: inputs.meanMotionDot,
		MEAN_MOTION_DDOT: inputs.meanMotionDdot
	};
	const satrec = json2satrec(omm);
	if (satrec.error !== SatRecError.None) {
		console.warn(
			`buildSatrec: SGP4 init failed for NORAD ${inputs.noradCatId} (error=${satrec.error})`
		);
		return null;
	}
	return satrec;
}

// `sgp4State` runs per frame for the one selected satellite, so a failure there
// is worth a line — but only the first, or it repeats for the life of the satrec.
const warnedSatrecs = new WeakSet<SatRec>();

/**
 * Propagate a satellite to the given Julian Date and return its TEME position in km.
 * Returns null on propagation failure (decayed sat, solver blowup) without
 * logging: a failure repeats every frame for the life of the satrec, so the
 * callers that load whole chunks report their drops as one tally instead.
 */
export function sgp4PositionTEME(satrec: SatRec, jd: number): [number, number, number] | null {
	const tsinceMin = (jd - satrec.jdsatepoch) * 1440;
	const result = sgp4(satrec, tsinceMin);
	if (!result || satrec.error !== SatRecError.None) return null;
	const { x, y, z } = result.position;
	return [x, y, z];
}

/**
 * TEME-frame position (km) → Three.js scene coordinates. Same obliquity
 * rotation as orbitalToThreeJS's equatorial branch, so SGP4 output lands in
 * the ecliptic frame the rest of the scene uses.
 */
export function temeKmToThreeJS(x: number, y: number, z: number): [number, number, number] {
	const scale = AU_SCALE / AU_KM;
	const xs = x * scale;
	let ys = y * scale;
	let zs = z * scale;
	// Rotate equatorial J2000 -> ecliptic J2000 about the shared X axis (vernal equinox)
	const yEcl = ys * COS_EPS + zs * SIN_EPS;
	const zEcl = -ys * SIN_EPS + zs * COS_EPS;
	ys = yEcl;
	zs = zEcl;
	// Ecliptic -> Three.js: ecliptic X -> X, ecliptic Z (north pole) -> Y, ecliptic Y -> -Z.
	return [xs, zs, -ys];
}

/**
 * One-shot helper combining propagation and frame conversion. Returns the
 * satellite's scene offset from Earth at `jd`, or null on failure.
 */
export function sgp4PositionScene(satrec: SatRec, jd: number): [number, number, number] | null {
	const teme = sgp4PositionTEME(satrec, jd);
	if (!teme) return null;
	return temeKmToThreeJS(teme[0], teme[1], teme[2]);
}

/**
 * Propagate to `jd`, returning radial distance (km) and speed (km/s). Mirrors
 * `currentStateFromElements` so satellite paths can swap in SGP4-accurate
 * values for altitude/speed displays; frame doesn't matter since both are rotation-invariant.
 */
export function sgp4State(satrec: SatRec, jd: number): { rKm: number; vKms: number } | null {
	const tsinceMin = (jd - satrec.jdsatepoch) * 1440;
	const result = sgp4(satrec, tsinceMin);
	if (!result || satrec.error !== SatRecError.None) {
		if (!warnedSatrecs.has(satrec)) {
			warnedSatrecs.add(satrec);
			console.warn(
				`sgp4State: propagation failed for NORAD ${satrec.satnum} (error=${satrec.error})`
			);
		}
		return null;
	}
	const { x, y, z } = result.position;
	const { x: vx, y: vy, z: vz } = result.velocity;
	return {
		rKm: Math.sqrt(x * x + y * y + z * z),
		vKms: Math.sqrt(vx * vx + vy * vy + vz * vz)
	};
}
