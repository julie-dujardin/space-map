import type { OrbitalElements } from '$lib/types/objects';
import { AU_KM, AU_SCALE } from './units';

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
 * Solve the hyperbolic Kepler equation M = e*sinh(H) - H for hyperbolic anomaly H.
 * Uses Newton-Raphson iteration.
 */
export function solveKeplerHyperbolic(
	M: number,
	e: number,
	tolerance = 1e-10,
	maxIter = 50
): number {
	// Initial guess: for small M use M, for large M use sign(M)*ln(2|M|/e)
	let H = Math.abs(M) < 1 ? M : Math.sign(M) * Math.log((2 * Math.abs(M)) / e);
	for (let i = 0; i < maxIter; i++) {
		const dH = (e * Math.sinh(H) - H - M) / (e * Math.cosh(H) - 1);
		H -= dH;
		if (Math.abs(dH) < tolerance) break;
	}
	return H;
}

/**
 * Rotate orbital-plane position (xOrb, yOrb) to Three.js coordinates.
 * Shared by elliptical and hyperbolic paths.
 */
function orbitalToThreeJS(
	xOrb: number,
	yOrb: number,
	w: number,
	i: number,
	om: number
): [number, number, number] {
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
 * Convert orbital elements to Cartesian position [x, y, z] in Three.js coordinates.
 *
 * Input: elements with angles in degrees, semi-major axis in AU.
 * Output: scaled Three.js coordinates where ecliptic plane = XZ plane, Y = up (north ecliptic pole).
 *
 * Supports elliptical (e < 1) and hyperbolic (e >= 1) orbits.
 * For hyperbolic orbits, a is negative (JPL convention).
 */
export function orbitalElementsToPosition(
	el: OrbitalElements,
	date: Date = new Date()
): [number, number, number] {
	const { a, e, i, om, w, ma, n, epoch } = el;

	// Propagate mean anomaly from epoch to requested date
	const dt = dateToJD(date) - epoch; // days since epoch
	const M = (ma + n * dt) * DEG2RAD;

	let nu: number;
	let r: number;

	if (e < 1) {
		// Elliptical orbit
		const E = solveKepler(M, e);
		const sinNu = (Math.sqrt(1 - e * e) * Math.sin(E)) / (1 - e * Math.cos(E));
		const cosNu = (Math.cos(E) - e) / (1 - e * Math.cos(E));
		nu = Math.atan2(sinNu, cosNu);
		r = a * (1 - e * Math.cos(E));
	} else {
		// Hyperbolic orbit (a < 0, e > 1; also covers near-parabolic e ≈ 1)
		const H = solveKeplerHyperbolic(M, e);
		const denom = e * Math.cosh(H) - 1;
		const sinNu = (Math.sqrt(e * e - 1) * Math.sinh(H)) / denom;
		const cosNu = (e - Math.cosh(H)) / denom;
		nu = Math.atan2(sinNu, cosNu);
		r = a * (1 - e * Math.cosh(H)); // a < 0 → r > 0
	}

	// Position in orbital plane
	const xOrb = r * Math.cos(nu);
	const yOrb = r * Math.sin(nu);

	return orbitalToThreeJS(xOrb, yOrb, w, i, om);
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
		// Sample uniformly in eccentric anomaly E for near-uniform arc spacing.
		// Mean anomaly sampling (M = j/n * 360) produces wildly unequal spacing for
		// high-eccentricity orbits: points cluster near aphelion and are sparse near
		// perihelion. E-uniform sampling keeps spacing roughly constant everywhere.
		const E = (j / numPoints) * 2 * Math.PI; // eccentric anomaly in radians
		// Kepler's equation: M = E - e*sin(E)
		const ma = (E - el.e * Math.sin(E)) * (180 / Math.PI);
		points.push(orbitalElementsToPosition({ ...el, ma, n: 0 }));
	}
	return points;
}

/**
 * Generate points along a hyperbolic trajectory for rendering orbit lines.
 * Returns an open curve (not closed) in Three.js coordinates.
 *
 * The curve extends to a maximum distance of `rMaxAU` from the focus.
 */
export function orbitalElementsToHyperbola(
	el: OrbitalElements,
	numPoints = 512,
	rMaxAU = 50
): [number, number, number][] {
	const absA = Math.abs(el.a);
	// H where r = rMax: r = |a|*(e*cosh(H) - 1), so cosh(H) = (rMax/|a| + 1) / e
	const coshMax = absA > 0 ? (rMaxAU / absA + 1) / el.e : 100;
	const Hmax = Math.min(Math.acosh(Math.max(coshMax, 1)), 6); // cap to avoid huge curves

	const points: [number, number, number][] = [];
	for (let j = 0; j <= numPoints; j++) {
		const H = -Hmax + (2 * Hmax * j) / numPoints;
		// Hyperbolic Kepler: M = e*sinh(H) - H
		const ma = (el.e * Math.sinh(H) - H) * (180 / Math.PI);
		points.push(orbitalElementsToPosition({ ...el, ma, n: 0 }));
	}
	return points;
}

/**
 * Generate orbit/trajectory curve points, dispatching to ellipse or hyperbola
 * based on eccentricity.
 */
export function orbitalElementsToCurve(
	el: OrbitalElements,
	numPoints = 512
): [number, number, number][] {
	if (el.e >= 1) return orbitalElementsToHyperbola(el, numPoints);
	return orbitalElementsToEllipse(el, numPoints);
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

	const elements: OrbitalElements = {
		a: a / AU_KM,
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
