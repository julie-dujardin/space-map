import type { OrbitalElements } from '$lib/types/objects';
import { AU_KM } from '$lib/math/units';
import { solveBarker, solveKepler, solveKeplerHyperbolic } from './solvers';

const DEG2RAD = Math.PI / 180;
const RAD2DEG = 180 / Math.PI;
const SEC_PER_DAY = 86400;
// Gaussian gravitational constant: sqrt(GM_sun) with GM in AU^3/day^2.
const GAUSS_K = 0.01720209895;
const AU_PER_DAY_TO_KM_PER_SEC = AU_KM / SEC_PER_DAY;

/**
 * Orbital radius (km) and speed (km/s) via vis-viva. GM comes from Kepler's
 * third law (GM = n² a³) for elliptical/hyperbolic orbits, or the assumed
 * heliocentric GAUSS_K² for parabolic (e ≈ 1, no a). Null on non-finite elements.
 */
export function currentStateFromElements(
	el: OrbitalElements,
	jd: number
): { rKm: number; vKms: number } | null {
	const { a, e, ma, n, epoch, q, tp } = el;

	// Parabolic: no semi-major axis / mean motion; use Barker + heliocentric GM.
	if (!isFinite(a) || a === 0 || !isFinite(n) || n <= 0) {
		if (q == null || tp == null || !isFinite(q) || !isFinite(tp) || q <= 0) {
			console.warn(`currentStateFromElements: skipped, non-finite elements`, el);
			return null;
		}
		const result = solveBarker(q, tp, jd);
		if (!result) return null;
		const rKm = result.r * AU_KM;
		// v² = GM · 2/r (1/a = 0 for parabolic); GM = k² in AU³/day².
		const vAuPerDay = GAUSS_K * Math.sqrt(2 / result.r);
		return { rKm, vKms: vAuPerDay * AU_PER_DAY_TO_KM_PER_SEC };
	}

	if (!isFinite(e) || !isFinite(ma)) {
		console.warn(`currentStateFromElements: skipped, non-finite elements`, el);
		return null;
	}

	const aKm = Math.abs(a) * AU_KM;
	const nRadPerSec = (n * DEG2RAD) / SEC_PER_DAY;
	const gm = nRadPerSec * nRadPerSec * aKm * aKm * aKm; // km^3/s^2

	const dt = jd - epoch;
	const M = (ma + n * dt) * DEG2RAD;

	let rAu: number;
	if (e < 1 || a > 0) {
		const eClamped = Math.min(e, 1 - 1e-7);
		const E = solveKepler(M, eClamped);
		rAu = a * (1 - eClamped * Math.cos(E));
	} else {
		const H = solveKeplerHyperbolic(M, e);
		if (!isFinite(H)) {
			console.warn(`currentStateFromElements: hyperbolic solver failed M=${M} e=${e}`);
			return null;
		}
		rAu = a * (1 - e * Math.cosh(H)); // a < 0 → rAu > 0
	}

	const rKm = rAu * AU_KM;
	if (!isFinite(rKm) || rKm <= 0) {
		console.warn(`currentStateFromElements: non-positive r=${rKm}`);
		return null;
	}

	// Vis-viva; with a < 0 (hyperbolic), the −1/a term is positive.
	const aSigned = a * AU_KM;
	const vSq = gm * (2 / rKm - 1 / aSigned);
	if (!isFinite(vSq) || vSq < 0) {
		console.warn(`currentStateFromElements: invalid v² = ${vSq}`);
		return null;
	}

	return { rKm, vKms: Math.sqrt(vSq) };
}

// Below this, treat e or sin(i) as zero and pin the undefined Ω/ω to 0.
// Generous on purpose: Float32 Chebyshev-fit noise can give e ~ 1e-7 even for
// a circular orbit, and a tighter threshold makes Ω/ω jitter between frames
// as the noise-level eccentricity vector rotates. Pinning is visually
// invisible since the drawn ellipse is symmetric in these degrees of freedom.
const SMALL_E = 1e-9;
const SMALL_SIN_I = 1e-9;

function clamp(x: number, lo: number, hi: number): number {
	return x < lo ? lo : x > hi ? hi : x;
}

/**
 * Osculating Keplerian elements from a parent-relative state vector. `r`
 * (AU) is in the frame whose z-axis is the orbit's reference normal —
 * ECLIPJ2000 for chebyshev callers, so elements come back `equatorial: false`.
 * `v` is AU/day, `muAuDay2` is AU³/day², `jd` becomes both epoch and the mean
 * anomaly's reference time.
 *
 * Null for parabolic-ish states (1/a ≈ 0; chebyshev bodies orbit stably, so
 * this is purely defensive). Hyperbolic states (a < 0, e > 1) get negative
 * `a` per JPL convention.
 *
 * Degenerate cases: e ≈ 0 pins ω to 0 (ν becomes argument of latitude, or
 * true longitude if also equatorial); sin(i) ≈ 0 pins Ω to 0 (ω becomes
 * longitude of perihelion, reflected for retrograde equatorial orbits so
 * propagation matches the input v).
 */
export function stateVectorToElements(
	r: [number, number, number],
	v: [number, number, number],
	muAuDay2: number,
	jd: number
): OrbitalElements | null {
	const [rx, ry, rz] = r;
	const [vx, vy, vz] = v;
	const rNorm = Math.hypot(rx, ry, rz);
	const v2 = vx * vx + vy * vy + vz * vz;
	if (rNorm === 0 || muAuDay2 <= 0 || !isFinite(rNorm) || !isFinite(v2)) return null;

	// Specific angular momentum h = r × v.
	const hx = ry * vz - rz * vy;
	const hy = rz * vx - rx * vz;
	const hz = rx * vy - ry * vx;
	const hNorm = Math.hypot(hx, hy, hz);
	if (hNorm === 0) return null; // Radial trajectory — no orbit plane.

	// Inclination.
	const iRad = Math.acos(clamp(hz / hNorm, -1, 1));
	const sinI = Math.sin(iRad);

	// Eccentricity vector e_vec = (v × h) / μ − r̂.
	const evX = (vy * hz - vz * hy) / muAuDay2 - rx / rNorm;
	const evY = (vz * hx - vx * hz) / muAuDay2 - ry / rNorm;
	const evZ = (vx * hy - vy * hx) / muAuDay2 - rz / rNorm;
	const e = Math.hypot(evX, evY, evZ);

	// Semi-major axis from vis-viva: 1/a = 2/|r| − v²/μ.
	const invA = 2 / rNorm - v2 / muAuDay2;
	if (Math.abs(invA) < 1e-12) return null; // Parabolic-ish: no Kepler representation here.
	const a = 1 / invA;

	// Node vector n = ẑ × h, lying along the ascending node when sin(i) ≠ 0.
	const nx = -hy;
	const ny = hx;
	const nNorm = Math.hypot(nx, ny);

	// Right ascension of ascending node Ω.
	let omRad: number;
	if (sinI < SMALL_SIN_I || nNorm === 0) {
		omRad = 0;
	} else {
		omRad = Math.acos(clamp(nx / nNorm, -1, 1));
		if (ny < 0) omRad = 2 * Math.PI - omRad;
	}

	// Argument of perihelion ω.
	let wRad: number;
	if (e < SMALL_E) {
		wRad = 0;
	} else if (sinI < SMALL_SIN_I || nNorm === 0) {
		// Equatorial: longitude of perihelion. Retrograde orbits flip so the
		// propagated direction (set by ω + ν advancing with mean motion) matches
		// the sign of the input angular momentum.
		wRad = Math.atan2(evY, evX);
		if (hz < 0) wRad = -wRad;
		if (wRad < 0) wRad += 2 * Math.PI;
	} else {
		const cosW = (nx * evX + ny * evY) / (nNorm * e);
		wRad = Math.acos(clamp(cosW, -1, 1));
		if (evZ < 0) wRad = 2 * Math.PI - wRad;
	}

	// True anomaly ν.
	let nuRad: number;
	const rDotV = rx * vx + ry * vy + rz * vz;
	if (e < SMALL_E && (sinI < SMALL_SIN_I || nNorm === 0)) {
		// Circular equatorial: true longitude.
		nuRad = Math.atan2(ry, rx);
		if (hz < 0) nuRad = -nuRad;
		if (nuRad < 0) nuRad += 2 * Math.PI;
	} else if (e < SMALL_E) {
		// Circular inclined: argument of latitude (angle from ascending node).
		const cosU = (nx * rx + ny * ry) / (nNorm * rNorm);
		nuRad = Math.acos(clamp(cosU, -1, 1));
		if (rz < 0) nuRad = 2 * Math.PI - nuRad;
	} else {
		const cosNu = (evX * rx + evY * ry + evZ * rz) / (e * rNorm);
		nuRad = Math.acos(clamp(cosNu, -1, 1));
		if (rDotV < 0) nuRad = 2 * Math.PI - nuRad;
	}

	// Mean anomaly from true anomaly.
	let maRad: number;
	if (e < 1) {
		const ERad =
			2 *
			Math.atan2(Math.sqrt(1 - e) * Math.sin(nuRad / 2), Math.sqrt(1 + e) * Math.cos(nuRad / 2));
		maRad = ERad - e * Math.sin(ERad);
	} else if (e > 1) {
		const HRad = 2 * Math.atanh(Math.sqrt((e - 1) / (e + 1)) * Math.tan(nuRad / 2));
		if (!isFinite(HRad)) return null;
		maRad = e * Math.sinh(HRad) - HRad;
	} else {
		return null;
	}

	// Mean motion: n = sqrt(μ/|a|³), in rad/day → deg/day.
	const aAbs = Math.abs(a);
	const nMotionDegPerDay = Math.sqrt(muAuDay2 / (aAbs * aAbs * aAbs)) * RAD2DEG;

	return {
		a,
		e,
		i: iRad * RAD2DEG,
		om: omRad * RAD2DEG,
		w: wRad * RAD2DEG,
		ma: maRad * RAD2DEG,
		n: nMotionDegPerDay,
		epoch: jd,
		equatorial: false
	};
}
