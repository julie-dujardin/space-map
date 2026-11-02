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
import { elementsJd, propagateOrbitAngles } from '$lib/math/orbit/position';
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
	/** μ of the orbit, km³/s²: n²a³, or the Sun's on a parabola. */
	mu: number;
}

/**
 * The rotation from the orbit plane to ecliptic J2000, as its six non-trivial
 * terms. Built once and applied to both position and velocity, since they
 * share an orbit — this is six trig calls, most of what turning elements into
 * a state costs, done tens of thousands of times by the porkchop and
 * swing-by search. Mirrors the rotation inside `orbitalToThreeJS` but stops
 * at the ecliptic; the scene's axis remap belongs to rendering, not physics.
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
 * Speed and motion both read `n` and `a`, so that a body moves as the map draws
 * it, whatever its central mass. A parabola has neither. Only a heliocentric
 * comet has one, so it takes the Sun's μ. Null when the elements are unusable.
 */
export function elementsToState(el: OrbitalElements, jd: number): StateVector | null {
	const { a, e, ma, n, epoch, q, tp } = el;
	const t = elementsJd(el, jd);
	const { om, w } = propagateOrbitAngles(el, jd);
	const equatorial = el.equatorial ?? false;

	if (!isFinite(a) || a === 0 || !isFinite(n) || n <= 0) {
		if (q == null || tp == null || !isFinite(q) || !isFinite(tp) || q <= 0) return null;
		const solved = solveBarker(q, tp, t);
		if (!solved) return null;
		const rKm = solved.r * AU_KM;
		const pKm = 2 * q * AU_KM; // semi-latus rectum of a parabola
		return buildState(rKm, solved.nu, pKm, 1, GM_SUN_KM3_S2, w, el.i, om, equatorial);
	}

	if (!isFinite(e) || !isFinite(ma)) return null;

	const aKm = a * AU_KM;
	const nRadPerSec = (n * DEG2RAD) / SEC_PER_DAY;
	const mu = nRadPerSec * nRadPerSec * Math.abs(aKm) * Math.abs(aKm) * Math.abs(aKm);
	if (!isFinite(mu) || mu <= 0) return null;

	const M = (ma + n * (t - epoch)) * DEG2RAD;

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
