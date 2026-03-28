import type { OrbitalElements } from './types';
import { AU_SCALE } from './constants';

const DEG2RAD = Math.PI / 180;

/** Convert a JS Date to Julian Date. */
export function dateToJD(date: Date): number {
	return date.getTime() / 86400000 + 2440587.5;
}

/**
 * Solve Kepler's equation M = E - e*sin(E) for eccentric anomaly E.
 * Uses Newton-Raphson iteration.
 */
export function solveKepler(M: number, e: number, tolerance = 1e-10, maxIter = 50): number {
	let E = M; // initial guess
	for (let i = 0; i < maxIter; i++) {
		const dE = (E - e * Math.sin(E) - M) / (1 - e * Math.cos(E));
		E -= dE;
		if (Math.abs(dE) < tolerance) break;
	}
	return E;
}

/**
 * Convert orbital elements to Cartesian position [x, y, z] in Three.js coordinates.
 *
 * Input: elements with angles in degrees, semi-major axis in AU.
 * Output: scaled Three.js coordinates where ecliptic plane = XZ plane, Y = up (north ecliptic pole).
 */
export function orbitalElementsToPosition(
	el: OrbitalElements,
	date: Date = new Date()
): [number, number, number] {
	const { a, e, i, om, w, ma, n, epoch } = el;

	// Propagate mean anomaly from epoch to requested date
	const dt = dateToJD(date) - epoch; // days since epoch
	const M = (ma + n * dt) * DEG2RAD;
	const E = solveKepler(M, e);

	// True anomaly
	const sinNu = (Math.sqrt(1 - e * e) * Math.sin(E)) / (1 - e * Math.cos(E));
	const cosNu = (Math.cos(E) - e) / (1 - e * Math.cos(E));
	const nu = Math.atan2(sinNu, cosNu);

	// Distance from focus
	const r = a * (1 - e * Math.cos(E));

	// Position in orbital plane
	const xOrb = r * Math.cos(nu);
	const yOrb = r * Math.sin(nu);

	// Rotation angles
	const cosW = Math.cos(w * DEG2RAD);
	const sinW = Math.sin(w * DEG2RAD);
	const cosI = Math.cos(i * DEG2RAD);
	const sinI = Math.sin(i * DEG2RAD);
	const cosOm = Math.cos(om * DEG2RAD);
	const sinOm = Math.sin(om * DEG2RAD);

	// Rotate to ecliptic J2000 frame
	const xEcl =
		(cosOm * cosW - sinOm * sinW * cosI) * xOrb + (-cosOm * sinW - sinOm * cosW * cosI) * yOrb;
	const yEcl =
		(sinOm * cosW + cosOm * sinW * cosI) * xOrb + (-sinOm * sinW + cosOm * cosW * cosI) * yOrb;
	const zEcl = sinW * sinI * xOrb + cosW * sinI * yOrb;

	// Map ecliptic -> Three.js: ecliptic X -> X, ecliptic Z (north pole) -> Y, ecliptic Y -> Z
	return [xEcl * AU_SCALE, zEcl * AU_SCALE, yEcl * AU_SCALE];
}

/**
 * Generate points along the full orbit ellipse for rendering orbit lines.
 * Returns array of [x, y, z] in Three.js coordinates.
 */
export function orbitalElementsToEllipse(
	el: OrbitalElements,
	numPoints = 128
): [number, number, number][] {
	const points: [number, number, number][] = [];
	for (let j = 0; j <= numPoints; j++) {
		const ma = (j / numPoints) * 360;
		// Use n=0 so orbitalElementsToPosition doesn't propagate the swept ma
		points.push(orbitalElementsToPosition({ ...el, ma, n: 0 }));
	}
	return points;
}

/**
 * Compute a rough position for an Earth satellite from mean elements.
 * Returns [x, y, z] in Three.js coordinates relative to Earth's position.
 *
 * Uses Kepler's third law with Earth's GM to derive semi-major axis from mean motion,
 * then standard Kepler conversion. The result is in km, then converted to AU for scene positioning.
 */
export function satelliteToOffset(sat: {
	meanMotion: number;
	eccentricity: number;
	inclination: number;
	raan: number;
	argOfPericenter: number;
	meanAnomaly: number;
}): [number, number, number] {
	const GM_EARTH = 398600.4418; // km^3/s^2
	const n = (sat.meanMotion * 2 * Math.PI) / 86400; // rad/s
	const a = Math.cbrt(GM_EARTH / (n * n)); // km

	const KM_PER_AU = 149597870.7;

	const elements: OrbitalElements = {
		a: a / KM_PER_AU,
		e: sat.eccentricity,
		i: sat.inclination,
		om: sat.raan,
		w: sat.argOfPericenter,
		ma: sat.meanAnomaly,
		n: 0,
		epoch: 0
	};

	return orbitalElementsToPosition(elements);
}
