import type { OrbitalElements } from '$lib/types/objects';
import { dateToJD } from '$lib/format/date';
import { AU_KM } from '$lib/math/units';
import { solveKepler, solveKeplerHyperbolic } from './solvers';

const DEG2RAD = Math.PI / 180;
const SEC_PER_DAY = 86400;

/**
 * Current orbital radius (km from parent) and speed (km/s) derived from elements
 * via vis-viva. GM is recovered from Kepler's third law (GM = n² a³) using the
 * supplied mean motion, so no parent-GM lookup is needed.
 *
 * Returns null for parabolic orbits (no a) or when elements are non-finite.
 */
export function currentStateFromElements(
	el: OrbitalElements,
	date: Date = new Date()
): { rKm: number; vKms: number } | null {
	const { a, e, ma, n, epoch } = el;

	if (!isFinite(a) || !isFinite(e) || !isFinite(ma) || !isFinite(n) || n <= 0 || a === 0) {
		console.warn(`currentStateFromElements: skipped, non-finite or parabolic elements`, el);
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
