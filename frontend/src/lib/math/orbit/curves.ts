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
	// Concentrate samples near perihelion by warping the E sweep: u ∈ [-1,1] uniform,
	// E = π·sign(u)·|u|^p. p=1 reproduces uniform E; raising p with e packs points
	// into the visually dominant perihelion arc instead of spreading them across the
	// apoapsis reach (for e=0.995, a=186 AU the old uniform sweep left almost no
	// points in the ~1 AU perihelion region where the body actually appears).
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
 * Generate points along a hyperbolic trajectory for rendering trails.
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
		points.push(orbitalToThreeJS(xOrb, yOrb, el.w, el.i, el.om, el.equatorial));
	}
	return points;
}

export interface OrbitCurve {
	points: [number, number, number][];
	isOpen: boolean;
}

/**
 * Sample SGP4 across the orbital period ending at `jdEnd` to build a polyline
 * that reflects the same J2/drag perturbations as the live-propagated dot.
 *
 * The curve spans `[jdEnd - T, jdEnd]` — i.e. the past one orbital period — so
 * `curve[N]` is the satellite's current position and `curve[0]` is where it
 * was one period ago. `buildTrailPoints` then walks backwards from the body's
 * position through the curve to render the orbit.
 *
 * Rendered as a closed loop: spanning exactly one period means `curve[0]` ≈
 * `curve[N]` (they differ only by one period of drag/J2 drift, sub-pixel for
 * LEO), so the ellipse closes back onto the body.
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
export function orbitalElementsToCurve(el: OrbitalElements, numPoints = 512): OrbitCurve {
	// Bound orbits (a > 0 per JPL convention) always render as ellipses, even when
	// e is rounded to 1.0 in float32. This keeps the curve aligned with the body
	// position, which goes through the elliptic Kepler branch with the same eClamped.
	const bound = isFinite(el.a) && el.a > 0;
	if (!bound && el.q != null) {
		return { points: orbitalElementsToParabola(el, numPoints), isOpen: true };
	}
	if (!bound && el.e >= 1) {
		return { points: orbitalElementsToHyperbola(el, numPoints), isOpen: true };
	}
	return { points: orbitalElementsToEllipse(el, numPoints), isOpen: false };
}
