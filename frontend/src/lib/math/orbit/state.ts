import type { OrbitalElements } from '$lib/types/objects';
import { dateToJD } from '$lib/format/date';
import { AU_KM } from '$lib/math/units';
import { solveBarker, solveKepler, solveKeplerHyperbolic } from './solvers';

const DEG2RAD = Math.PI / 180;
const SEC_PER_DAY = 86400;
// Gaussian gravitational constant: sqrt(GM_sun) with GM in AU^3/day^2.
const GAUSS_K = 0.01720209895;
const AU_PER_DAY_TO_KM_PER_SEC = AU_KM / SEC_PER_DAY;

/**
 * Current orbital radius (km from parent) and speed (km/s) derived from elements
 * via vis-viva. For elliptical/hyperbolic orbits GM is recovered from Kepler's
 * third law (GM = n² a³) using the supplied mean motion. For parabolic orbits
 * (e ≈ 1, no a) the heliocentric GM is assumed (GAUSS_K²).
 *
 * Returns null when required elements are non-finite.
 */
export function currentStateFromElements(
	el: OrbitalElements,
	date: Date = new Date()
): { rKm: number; vKms: number } | null {
	const { a, e, ma, n, epoch, q, tp } = el;

	// Parabolic: no semi-major axis / mean motion; use Barker + heliocentric GM.
	if (!isFinite(a) || a === 0 || !isFinite(n) || n <= 0) {
		if (q == null || tp == null || !isFinite(q) || !isFinite(tp) || q <= 0) {
			console.warn(`currentStateFromElements: skipped, non-finite elements`, el);
			return null;
		}
		const result = solveBarker(q, tp, dateToJD(date));
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

	const dt = dateToJD(date) - epoch;
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
