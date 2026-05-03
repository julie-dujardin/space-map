import type { OrbitalElements } from '$lib/types/objects';
import { dateToJD } from '$lib/format/date';
import { AU_SCALE, EARTH_OBLIQUITY_DEG } from '$lib/math/units';
import { solveKepler, solveKeplerHyperbolic, solveBarker } from './solvers';

const DEG2RAD = Math.PI / 180;
const COS_EPS = Math.cos(EARTH_OBLIQUITY_DEG * DEG2RAD);
const SIN_EPS = Math.sin(EARTH_OBLIQUITY_DEG * DEG2RAD);

/**
 * Rotate orbital-plane position (xOrb, yOrb) to Three.js coordinates.
 * Shared by position computation and curve generators.
 *
 * When `equatorial` is true, i/om/w are interpreted in Earth's mean equator
 * of J2000 (TEME, as used by TLEs) and the result is rotated by the obliquity
 * onto the ecliptic — otherwise Earth-orbit satellites would align to the
 * ecliptic's poles instead of Earth's.
 */
export function orbitalToThreeJS(
	xOrb: number,
	yOrb: number,
	w: number,
	i: number,
	om: number,
	equatorial = false
): [number, number, number] {
	const cosW = Math.cos(w * DEG2RAD);
	const sinW = Math.sin(w * DEG2RAD);
	const cosI = Math.cos(i * DEG2RAD);
	const sinI = Math.sin(i * DEG2RAD);
	const cosOm = Math.cos(om * DEG2RAD);
	const sinOm = Math.sin(om * DEG2RAD);

	// Resolve the orbital plane into the reference frame of the input angles:
	// ecliptic J2000 by default, Earth-equatorial J2000 when `equatorial`.
	const x =
		(cosOm * cosW - sinOm * sinW * cosI) * xOrb + (-cosOm * sinW - sinOm * cosW * cosI) * yOrb;
	let y =
		(sinOm * cosW + cosOm * sinW * cosI) * xOrb + (-sinOm * sinW + cosOm * cosW * cosI) * yOrb;
	let z = sinW * sinI * xOrb + cosW * sinI * yOrb;

	if (equatorial) {
		// Rotate equatorial J2000 -> ecliptic J2000 about the shared X axis (vernal
		// equinox) by the obliquity ε. Only y/z move; x is invariant.
		const yEcl = y * COS_EPS + z * SIN_EPS;
		const zEcl = -y * SIN_EPS + z * COS_EPS;
		y = yEcl;
		z = zEcl;
	}

	// Map ecliptic -> Three.js: ecliptic X -> X, ecliptic Z (north pole) -> Y, ecliptic Y -> -Z.
	// The Y -> -Z flip keeps the mapping handedness-preserving (det +1), so body spin
	// computed via the right-hand rule matches physical rotation direction.
	return [x * AU_SCALE, z * AU_SCALE, -y * AU_SCALE];
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
	return orbitalElementsToPositionJD(el, dateToJD(date));
}

/** JD-based variant of {@link orbitalElementsToPosition}. Avoids Date allocation in hot loops. */
export function orbitalElementsToPositionJD(
	el: OrbitalElements,
	jd: number
): [number, number, number] | null {
	const { a, e, i, om, w, ma, n, epoch, omDot, wDot } = el;

	if (!isFinite(a) || !isFinite(e) || !isFinite(ma) || !isFinite(n)) {
		console.warn(`NaN in orbital elements: a=${a} e=${e} ma=${ma} n=${n}`);
		return null;
	}

	// Propagate mean anomaly from epoch to requested date
	const dt = jd - epoch; // days since epoch
	const M = (ma + n * dt) * DEG2RAD;
	// Secular drift on the node and apsidal angles. SPICE moons get om_dot/w_dot
	// from the Method C mean-element fit, capturing J2-driven precession that
	// the static-angle Kepler step would miss. Other sources leave the rates
	// undefined (or zero) so the offset reduces to no-op.
	const omPropagated = omDot ? om + omDot * dt : om;
	const wPropagated = wDot ? w + wDot * dt : w;

	// Truly parabolic comets (e ≈ 1, unbound) come through parabolicToPositionJD
	// with explicit q/tp and bypass this function. Bound orbits with e rounded
	// to 1 in float32 (e.g. the SPICE Sun: a=0.003 AU, e≈1−7e−10) go through
	// the elliptic branch below with eClamped — stable for all M and gives a
	// bounded r. Barker must not run on bound orbits: it assumes r → ∞ away
	// from perihelion, producing multi-AU flickers each time the body
	// (e.g. the Sun) crosses the near-perihelion band in mean anomaly.

	let nu: number;
	let r: number;

	if (e < 1 || a > 0) {
		// Elliptical orbit (or e rounded-to-1 on a closed orbit per JPL convention).
		// Clamp e just below 1 so 1-e² stays positive and the solver doesn't divide
		// by zero at perihelion. Away from perihelion this is numerically harmless.
		const eClamped = Math.min(e, 1 - 1e-7);
		const E = solveKepler(M, eClamped);
		const sinNu = (Math.sqrt(1 - eClamped * eClamped) * Math.sin(E)) / (1 - eClamped * Math.cos(E));
		const cosNu = (Math.cos(E) - eClamped) / (1 - eClamped * Math.cos(E));
		nu = Math.atan2(sinNu, cosNu);
		r = a * (1 - eClamped * Math.cos(E));
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

	return orbitalToThreeJS(xOrb, yOrb, wPropagated, i, omPropagated, el.equatorial);
}

/**
 * Convert parabolic orbital elements to Cartesian position using Barker's equation.
 * Requires el.q (perihelion distance) and el.tp (time of perihelion).
 */
export function parabolicToPosition(
	el: OrbitalElements,
	date: Date = new Date()
): [number, number, number] | null {
	return parabolicToPositionJD(el, dateToJD(date));
}

/** JD-based variant of {@link parabolicToPosition}. Avoids Date allocation in hot loops. */
export function parabolicToPositionJD(
	el: OrbitalElements,
	jd: number
): [number, number, number] | null {
	const { q, tp, i, om, w } = el;
	if (q == null || tp == null || !isFinite(q) || !isFinite(tp)) {
		return null;
	}

	const result = solveBarker(q, tp, jd);
	if (!result) return null;

	const xOrb = result.r * Math.cos(result.nu);
	const yOrb = result.r * Math.sin(result.nu);
	if (!isFinite(xOrb) || !isFinite(yOrb)) return null;

	return orbitalToThreeJS(xOrb, yOrb, w, i, om, el.equatorial);
}
