import type { OrbitalElements } from '$lib/types/objects';
import { dateToJD } from '$lib/format/date';
import { AU_KM, AU_SCALE } from '$lib/math/units';
import { solveKepler, solveKeplerHyperbolic, solveBarker } from './solvers';

const DEG2RAD = Math.PI / 180;

/**
 * Rotate orbital-plane position (xOrb, yOrb) to Three.js coordinates.
 * Shared by position computation and curve generators.
 */
export function orbitalToThreeJS(
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
): [number, number, number] | null {
	const { a, e, i, om, w, ma, n, epoch } = el;

	if (!isFinite(a) || !isFinite(e) || !isFinite(ma) || !isFinite(n)) {
		console.warn(`NaN in orbital elements: a=${a} e=${e} ma=${ma} n=${n}`);
		return null;
	}

	// Propagate mean anomaly from epoch to requested date
	const dt = dateToJD(date) - epoch; // days since epoch
	const M = (ma + n * dt) * DEG2RAD;

	// Near-parabolic orbits (|e − 1| < 0.01): the hyperbolic/elliptical Kepler
	// solvers are ill-conditioned here (denominator e·cosh(H)−1 ≈ 0 causes
	// Newton-Raphson to overshoot). Fall back to Barker's equation with
	// q and tp derived from the standard elements.
	// See spkid-1001113 C/1962 C1 (Seki-Lines)
	// Skip for tiny orbits (a < 0.001 AU): numerical instability is negligible
	// at that scale, and planets orbiting their barycenters can have spurious
	// high eccentricity (e.g. Jupiter e≈0.996 around its barycenter).
	if (Math.abs(e - 1) < 0.01 && Math.abs(a) >= 0.001) {
		const q = Math.abs(a) * Math.abs(1 - e); // works for both e<1 and e>1
		const tp = n !== 0 ? epoch - ma / n : epoch; // tp in JD (ma in deg, n in deg/day)
		const jd = dateToJD(date);
		const result = solveBarker(q, tp, jd);
		if (!result) return null;
		const xOrb = result.r * Math.cos(result.nu);
		const yOrb = result.r * Math.sin(result.nu);
		if (!isFinite(xOrb) || !isFinite(yOrb)) return null;
		return orbitalToThreeJS(xOrb, yOrb, w, i, om);
	}

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
		if (!isFinite(H)) {
			console.warn(`solveKeplerHyperbolic overflow: M=${M} e=${e}`);
			return null;
		}
		const denom = e * Math.cosh(H) - 1;
		if (Math.abs(denom) < 1e-15) {
			console.warn(`Hyperbolic denom near zero: H=${H} e=${e} denom=${denom}`);
			return null;
		}
		const sinNu = (Math.sqrt(e * e - 1) * Math.sinh(H)) / denom;
		const cosNu = (e - Math.cosh(H)) / denom;
		nu = Math.atan2(sinNu, cosNu);
		r = a * (1 - e * Math.cosh(H)); // a < 0 → r > 0
	}

	// Position in orbital plane
	const xOrb = r * Math.cos(nu);
	const yOrb = r * Math.sin(nu);
	if (!isFinite(xOrb) || !isFinite(yOrb)) {
		console.warn(
			`Non-finite orbital position: r=${r} nu=${nu} xOrb=${xOrb} yOrb=${yOrb} a=${a} e=${e}`
		);
		return null;
	}

	return orbitalToThreeJS(xOrb, yOrb, w, i, om);
}

/**
 * Convert parabolic orbital elements to Cartesian position using Barker's equation.
 * Requires el.q (perihelion distance) and el.tp (time of perihelion).
 */
export function parabolicToPosition(
	el: OrbitalElements,
	date: Date = new Date()
): [number, number, number] | null {
	const { q, tp, i, om, w } = el;
	if (q == null || tp == null || !isFinite(q) || !isFinite(tp)) {
		return null;
	}

	const jd = dateToJD(date);
	const result = solveBarker(q, tp, jd);
	if (!result) return null;

	const xOrb = result.r * Math.cos(result.nu);
	const yOrb = result.r * Math.sin(result.nu);
	if (!isFinite(xOrb) || !isFinite(yOrb)) return null;

	return orbitalToThreeJS(xOrb, yOrb, w, i, om);
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

	return orbitalElementsToPosition(elements) ?? [0, 0, 0];
}
