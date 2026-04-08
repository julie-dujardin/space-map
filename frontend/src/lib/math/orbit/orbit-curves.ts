import type { OrbitalElements } from '$lib/types/objects';
import { orbitalToThreeJS } from './position';

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
		// True parabolic (q set) or near-parabolic elliptic/hyperbolic: use the parabolic
		// renderer which concentrates all points near perihelion (capped at rMaxAU).
		// This gives much better visual density than spreading 512 points across a
		// 100+ AU ellipse where only the perihelion region is visible.
		const q = el.q ?? Math.abs(el.a) * Math.abs(1 - el.e);
		return { points: orbitalElementsToParabola({ ...el, q }, numPoints), isOpen: true };
	}
	if (el.e >= 1) return { points: orbitalElementsToHyperbola(el, numPoints), isOpen: true };
	return { points: orbitalElementsToEllipse(el, numPoints), isOpen: false };
}
