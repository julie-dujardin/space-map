import type { OrbitalElements } from '$lib/types/objects';
import { orbitalToThreeJS } from './position';
import { sgp4PositionScene } from './sgp4';
import type { SatRec } from 'satellite.js';

/**
 * Generate points along a parabolic trajectory for rendering trails.
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
		points.push(orbitalToThreeJS(xOrb, yOrb, el.w, el.i, el.om, el.equatorial));
	}
	return points;
}

/**
 * Generate points along the full orbit ellipse for rendering trails.
 * Returns array of [x, y, z] in Three.js coordinates.
 */
export function orbitalElementsToEllipse(
	el: OrbitalElements,
	numPoints = 128
): [number, number, number][] {
	const { a, i, om, w } = el;
	// Clamp e just below 1 so 1-e² stays positive for near-parabolic bound orbits
	// (matches the clamp in orbitalElementsToPositionJD, keeping curve and body aligned).
	const e = Math.min(el.e, 1 - 1e-7);
	// Warp uniform u ∈ [-1,1] to E = π·sign(u)·|u|^p so samples concentrate near
	// perihelion (raising p with e), where the body visually sits, not the apoapsis.
	const p = 1 + 3 * e;
	const sqrt1me2 = Math.sqrt(1 - e * e);
	const points: [number, number, number][] = [];
	for (let j = 0; j <= numPoints; j++) {
		const u = (2 * j) / numPoints - 1;
		const E = Math.PI * Math.sign(u) * Math.pow(Math.abs(u), p);
		const cosE = Math.cos(E);
		const sinE = Math.sin(E);
		const denom = 1 - e * cosE;
		const sinNu = (sqrt1me2 * sinE) / denom;
		const cosNu = (cosE - e) / denom;
		const nu = Math.atan2(sinNu, cosNu);
		const r = a * denom;
		const xOrb = r * Math.cos(nu);
		const yOrb = r * Math.sin(nu);
		if (!isFinite(xOrb) || !isFinite(yOrb)) continue;
		points.push(orbitalToThreeJS(xOrb, yOrb, w, i, om, el.equatorial));
	}
	return points;
}

/**
 * Open hyperbolic-trajectory polyline, Three.js coordinates, out to `rMaxAU`
 * from the focus. Computed directly from hyperbolic anomaly H, avoiding the
 * mean-anomaly/Newton-Raphson round-trip that can produce NaN.
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
		const denom = el.e * Math.cosh(H) - 1;
		if (Math.abs(denom) < 1e-15) continue; // skip degenerate point
		const sinNu = (Math.sqrt(el.e * el.e - 1) * Math.sinh(H)) / denom;
		const cosNu = (el.e - Math.cosh(H)) / denom;
		const nu = Math.atan2(sinNu, cosNu);
		const r = el.a * (1 - el.e * Math.cosh(H)); // a < 0 → r > 0
		const xOrb = r * Math.cos(nu);
		const yOrb = r * Math.sin(nu);
		points.push(orbitalToThreeJS(xOrb, yOrb, el.w, el.i, el.om, el.equatorial));
	}
	return points;
}

export interface OrbitCurve {
	points: [number, number, number][];
	isOpen: boolean;
}

/**
 * SGP4-sampled polyline over the period ending at `jdEnd`, so it carries the
 * same J2/drag perturbations as the live-propagated dot. Open: a sliding
 * window's ends never meet, and closing it draws a stray segment.
 */
export function sgp4Curve(
	satrec: SatRec,
	jdEnd: number,
	meanMotionRevPerDay: number,
	numPoints = 128
): [number, number, number][] {
	if (!isFinite(meanMotionRevPerDay) || meanMotionRevPerDay <= 0) return [];
	const periodDays = 1 / meanMotionRevPerDay;
	const points: [number, number, number][] = [];
	for (let j = 0; j <= numPoints; j++) {
		const jd = jdEnd - periodDays + (periodDays * j) / numPoints;
		const p = sgp4PositionScene(satrec, jd);
		if (p) points.push(p);
	}
	return points;
}

/**
 * Generate orbit/trajectory curve points, dispatching to ellipse, parabola,
 * or hyperbola based on eccentricity.
 */
/** Whether {@link orbitalElementsToCurve} draws these elements as an open arc. */
export function isOpenOrbit(el: OrbitalElements): boolean {
	const bound = isFinite(el.a) && el.a > 0;
	return !bound && (el.q != null || el.e >= 1);
}

export function orbitalElementsToCurve(el: OrbitalElements, numPoints = 512): OrbitCurve {
	// Bound orbits (a > 0, JPL convention) always render as ellipses, even if e
	// rounds to 1.0 in float32 — matches the body's elliptic Kepler branch.
	const bound = isFinite(el.a) && el.a > 0;
	if (!bound && el.q != null) {
		return { points: orbitalElementsToParabola(el, numPoints), isOpen: true };
	}
	if (!bound && el.e >= 1) {
		return { points: orbitalElementsToHyperbola(el, numPoints), isOpen: true };
	}
	return { points: orbitalElementsToEllipse(el, numPoints), isOpen: false };
}
