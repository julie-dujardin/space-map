import type { OrbitalElements } from '$lib/types/objects';
import { dateToJD } from '$lib/format/date';
import { AU_KM, AU_SCALE } from './units';

const DEG2RAD = Math.PI / 180;

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
 * Returns NaN if the solver fails to converge or overflows.
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
		const sH = Math.sinh(H);
		const cH = Math.cosh(H);
		if (!isFinite(sH) || !isFinite(cH)) return NaN;
		const dH = (e * sH - H - M) / (e * cH - 1);
		H -= dH;
		if (Math.abs(dH) < tolerance) break;
	}
	return H;
}

/**
 * Solve Barker's equation for parabolic orbits (e = 1).
 *
 * Given perihelion distance q [AU] and time of perihelion tp [JD],
 * returns [trueAnomaly, radius] at the given Julian date, or null
 * if the computation fails.
 *
 * Uses the standard cubic form:  W = tan(ν/2)/2 + tan³(ν/2)/6
 * where W = sqrt(GM_sun / (2 q³)) · (t − tp),
 * with GM_sun in AU³/day² = k² (k = 0.01720209895 rad/day, Gaussian gravitational constant).
 */
export function solveBarker(q: number, tp: number, jd: number): { nu: number; r: number } | null {
	const k = 0.01720209895; // Gaussian gravitational constant [AU^(3/2) / day]
	const dt = jd - tp; // days since perihelion
	const W = (k * dt) / (Math.sqrt(2) * Math.pow(q, 1.5));

	// Solve W = s + s³/3 where s = tan(ν/2), i.e. 3W = 3s + s³
	// Use the real cube-root solution (Barker's formula):
	// s = 2 cot(2 arctan(cbrt(3W)))  — but the direct cubic solution is simpler:
	const y = Math.cbrt(3 * W + Math.sqrt(1 + 9 * W * W));
	const s = y - 1 / y; // tan(ν/2)

	const nu = 2 * Math.atan(s);
	const r = q * (1 + s * s); // r = q(1 + tan²(ν/2)) = 2q/(1+cos ν)

	if (!isFinite(nu) || !isFinite(r) || r <= 0) return null;
	return { nu, r };
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
 * Generate points along a parabolic trajectory for rendering orbit lines.
 * Returns an open curve in Three.js coordinates.
 * Samples uniformly in true anomaly, capped at rMaxAU from the focus.
 */
export function orbitalElementsToParabola(
	el: OrbitalElements,
	numPoints = 512,
	rMaxAU = 50
): [number, number, number][] {
	const q = el.q ?? el.a;
	if (!isFinite(q) || q <= 0) return [];

	// r = 2q / (1 + cos ν), so cos(νMax) = 2q/rMax - 1
	const cosNuMax = Math.max((2 * q) / rMaxAU - 1, -0.999);
	const nuMax = Math.acos(cosNuMax);

	const points: [number, number, number][] = [];
	for (let j = 0; j <= numPoints; j++) {
		const nu = -nuMax + (2 * nuMax * j) / numPoints;
		const r = (2 * q) / (1 + Math.cos(nu));
		const xOrb = r * Math.cos(nu);
		const yOrb = r * Math.sin(nu);
		points.push(orbitalToThreeJS(xOrb, yOrb, el.w, el.i, el.om));
	}
	return points;
}

/**
 * Generate points along the full orbit ellipse for rendering orbit lines.
 * Returns array of [x, y, z] in Three.js coordinates.
 */
export function orbitalElementsToEllipse(
	el: OrbitalElements,
	numPoints = 128
): [number, number, number][] {
	const { a, e, i, om, w } = el;
	const points: [number, number, number][] = [];
	for (let j = 0; j <= numPoints; j++) {
		// Sample uniformly in eccentric anomaly E for near-uniform arc spacing.
		// Compute position directly from E to avoid the E→M→solveKepler→E round-trip
		// which diverges for high-eccentricity orbits (Newton-Raphson overshoots when
		// 1 - e·cos(E) ≈ 0 near perihelion).
		const E = (j / numPoints) * 2 * Math.PI;
		const sinNu = (Math.sqrt(1 - e * e) * Math.sin(E)) / (1 - e * Math.cos(E));
		const cosNu = (Math.cos(E) - e) / (1 - e * Math.cos(E));
		const nu = Math.atan2(sinNu, cosNu);
		const r = a * (1 - e * Math.cos(E));
		const xOrb = r * Math.cos(nu);
		const yOrb = r * Math.sin(nu);
		if (!isFinite(xOrb) || !isFinite(yOrb)) continue;
		points.push(orbitalToThreeJS(xOrb, yOrb, w, i, om));
	}
	return points;
}

/**
 * Generate points along a hyperbolic trajectory for rendering orbit lines.
 * Returns an open curve (not closed) in Three.js coordinates.
 *
 * Computes positions directly from the hyperbolic anomaly H, avoiding the
 * round-trip through mean anomaly and Newton-Raphson that can produce NaN.
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
		// Compute true anomaly and radius directly from H
		const denom = el.e * Math.cosh(H) - 1;
		if (Math.abs(denom) < 1e-15) continue; // skip degenerate point
		const sinNu = (Math.sqrt(el.e * el.e - 1) * Math.sinh(H)) / denom;
		const cosNu = (el.e - Math.cosh(H)) / denom;
		const nu = Math.atan2(sinNu, cosNu);
		const r = el.a * (1 - el.e * Math.cosh(H)); // a < 0 → r > 0
		const xOrb = r * Math.cos(nu);
		const yOrb = r * Math.sin(nu);
		points.push(orbitalToThreeJS(xOrb, yOrb, el.w, el.i, el.om));
	}
	return points;
}

export interface OrbitCurve {
	points: [number, number, number][];
	isOpen: boolean;
}

/**
 * Generate orbit/trajectory curve points, dispatching to ellipse, parabola,
 * or hyperbola based on eccentricity.
 */
export function orbitalElementsToCurve(el: OrbitalElements, numPoints = 512): OrbitCurve {
	if (el.q != null || (Math.abs(el.e - 1) < 0.01 && Math.abs(el.a) >= 0.001)) {
		const q = el.q ?? Math.abs(el.a) * Math.abs(1 - el.e);
		return { points: orbitalElementsToParabola({ ...el, q }, numPoints), isOpen: true };
	}
	if (el.e >= 1) return { points: orbitalElementsToHyperbola(el, numPoints), isOpen: true };
	return { points: orbitalElementsToEllipse(el, numPoints), isOpen: false };
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
