/**
 * Cartesian state vectors (position + velocity) from orbital elements.
 *
 * The renderer's `orbitalElementsToPositionJD` returns scene coordinates —
 * scaled, Y-up, with the ecliptic Y axis negated. Trajectory math needs a plain
 * physical frame instead, so this module works in **parent-centred ecliptic
 * J2000, km and km/s**, and offers an explicit converter for when a result has
 * to be drawn.
 */

import type { OrbitalElements } from '$lib/types/objects';
import { AU_KM, AU_SCALE, EARTH_OBLIQUITY_DEG } from '$lib/math/units';
import { propagateOrbitAngles } from '$lib/math/orbit/position';
import { solveBarker, solveKepler, solveKeplerHyperbolic } from '$lib/math/orbit/solvers';
import { GM_SUN_KM3_S2, SEC_PER_DAY } from './constants';
import type { Vec3 } from './vec3';

const DEG2RAD = Math.PI / 180;
const COS_EPS = Math.cos(EARTH_OBLIQUITY_DEG * DEG2RAD);
const SIN_EPS = Math.sin(EARTH_OBLIQUITY_DEG * DEG2RAD);

export interface StateVector {
	/** Position in the parent-centred ecliptic J2000 frame, km. */
	r: Vec3;
	/** Velocity in the same frame, km/s. */
	v: Vec3;
	/** Gravitational parameter the state was built with, km³/s². */
	mu: number;
}

/**
 * The rotation from the orbit plane to ecliptic J2000, as its six non-trivial
 * terms.
 *
 * Built once and applied to both the position and the velocity. They share an
 * orbit, so they share this — and it is six trigonometric calls, which is most
 * of what turning a set of elements into a state costs. The porkchop and the
 * swing-by search each do that tens of thousands of times.
 *
 * Mirrors the rotation inside `orbitalToThreeJS` but stops at the ecliptic —
 * the scene's axis remap belongs to rendering, not physics.
 */
interface PlaneRotation {
	m11: number;
	m12: number;
	m21: number;
	m22: number;
	m31: number;
	m32: number;
	equatorial: boolean;
}

function planeRotation(w: number, i: number, om: number, equatorial: boolean): PlaneRotation {
	const cosW = Math.cos(w * DEG2RAD);
	const sinW = Math.sin(w * DEG2RAD);
	const cosI = Math.cos(i * DEG2RAD);
	const sinI = Math.sin(i * DEG2RAD);
	const cosOm = Math.cos(om * DEG2RAD);
	const sinOm = Math.sin(om * DEG2RAD);

	return {
		m11: cosOm * cosW - sinOm * sinW * cosI,
		m12: -cosOm * sinW - sinOm * cosW * cosI,
		m21: sinOm * cosW + cosOm * sinW * cosI,
		m22: -sinOm * sinW + cosOm * cosW * cosI,
		m31: sinW * sinI,
		m32: cosW * sinI,
		equatorial
	};
}

/** Rotate an in-plane (perifocal) vector to ecliptic J2000. */
function perifocalToEcliptic(px: number, py: number, rot: PlaneRotation): Vec3 {
	const x = rot.m11 * px + rot.m12 * py;
	let y = rot.m21 * px + rot.m22 * py;
	let z = rot.m31 * px + rot.m32 * py;

	if (rot.equatorial) {
		// TLE-sourced elements are referenced to Earth's mean equator; rotate about
		// the shared vernal-equinox axis so they share a frame with everything else.
		const yEcl = y * COS_EPS + z * SIN_EPS;
		const zEcl = -y * SIN_EPS + z * COS_EPS;
		y = yEcl;
		z = zEcl;
	}

	return [x, y, z];
}

/** Ecliptic J2000 km → Three.js scene units, matching `orbitalToThreeJS`. */
export function eclipticToScene(r: Vec3): Vec3 {
	const k = AU_SCALE / AU_KM;
	return [r[0] * k, r[2] * k, -r[1] * k];
}

/**
 * Position and velocity at `jd`, in the parent-centred ecliptic J2000 frame.
 *
 * `muKm3S2` should be supplied whenever a trustworthy value exists (the SPICE
 * PCK GMs the export ships). Without it μ is recovered from Kepler's third law
 * using the packed mean motion, which is float32 in the binary and so carries
 * roughly seven digits — fine for a Δv estimate, not for ephemeris work.
 *
 * Mean anomaly is always propagated with the packed mean motion rather than one
 * re-derived from μ, so positions here agree with what the renderer draws.
 *
 * Returns null when the elements are unusable.
 */
export function elementsToState(
	el: OrbitalElements,
	jd: number,
	muKm3S2?: number
): StateVector | null {
	const { a, e, ma, n, epoch, q, tp } = el;
	const { om, w } = propagateOrbitAngles(el, jd);
	const equatorial = el.equatorial ?? false;

	// Parabolic elements carry q/tp instead of a/n, and only ever describe
	// heliocentric comets — hence the Sun's μ as the fallback.
	if (!isFinite(a) || a === 0 || !isFinite(n) || n <= 0) {
		if (q == null || tp == null || !isFinite(q) || !isFinite(tp) || q <= 0) return null;
		const solved = solveBarker(q, tp, jd);
		if (!solved) return null;
		const mu = muKm3S2 && muKm3S2 > 0 ? muKm3S2 : GM_SUN_KM3_S2;
		const rKm = solved.r * AU_KM;
		const pKm = 2 * q * AU_KM; // semi-latus rectum of a parabola
		return buildState(rKm, solved.nu, pKm, 1, mu, w, el.i, om, equatorial);
	}

	if (!isFinite(e) || !isFinite(ma)) return null;

	const aKm = a * AU_KM;
	const nRadPerSec = (n * DEG2RAD) / SEC_PER_DAY;
	const mu =
		muKm3S2 && muKm3S2 > 0
			? muKm3S2
			: nRadPerSec * nRadPerSec * Math.abs(aKm) * Math.abs(aKm) * Math.abs(aKm);
	if (!isFinite(mu) || mu <= 0) return null;

	const M = (ma + n * (jd - epoch)) * DEG2RAD;

	let nu: number;
	let rKm: number;
	if (e < 1 || a > 0) {
		const eC = Math.min(e, 1 - 1e-7);
		const E = solveKepler(M, eC);
		const denom = 1 - eC * Math.cos(E);
		nu = Math.atan2(Math.sqrt(1 - eC * eC) * Math.sin(E), Math.cos(E) - eC);
		rKm = aKm * denom;
	} else {
		const H = solveKeplerHyperbolic(M, e);
		if (!isFinite(H)) return null;
		const denom = e * Math.cosh(H) - 1;
		if (Math.abs(denom) < 1e-15) return null;
		nu = Math.atan2((Math.sqrt(e * e - 1) * Math.sinh(H)) / denom, (e - Math.cosh(H)) / denom);
		rKm = aKm * (1 - e * Math.cosh(H)); // a < 0 → r > 0
	}

	if (!isFinite(rKm) || rKm <= 0) return null;
	// p = a(1 − e²) stays positive on both branches (a < 0 pairs with e > 1).
	const pKm = aKm * (1 - e * e);
	if (!isFinite(pKm) || pKm <= 0) return null;

	return buildState(rKm, nu, pKm, e, mu, w, el.i, om, equatorial);
}

function buildState(
	rKm: number,
	nu: number,
	pKm: number,
	e: number,
	mu: number,
	w: number,
	i: number,
	om: number,
	equatorial: boolean
): StateVector | null {
	const cosNu = Math.cos(nu);
	const sinNu = Math.sin(nu);
	const h = Math.sqrt(mu / pKm);

	const rot = planeRotation(w, i, om, equatorial);
	const r = perifocalToEcliptic(rKm * cosNu, rKm * sinNu, rot);
	const v = perifocalToEcliptic(-h * sinNu, h * (e + cosNu), rot);

	if (!isFinite(r[0] + r[1] + r[2]) || !isFinite(v[0] + v[1] + v[2])) return null;
	return { r, v, mu };
}
