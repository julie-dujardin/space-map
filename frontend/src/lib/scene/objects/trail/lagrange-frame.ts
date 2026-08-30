/**
 * Sun–Earth Lagrange-point trails drawn co-rotating with the Sun–Earth line.
 * Trail samples are stored Earth-relative and inertial, which turns a halo
 * orbit into a smear that follows Earth around the Sun; the rotating frame
 * shows the loop around L1/L2 instead.
 */

const DEG = Math.PI / 180;
const J2000 = 2451545;
// Earth–Moon barycentre mean elements at J2000 (Standish, JPL approximate
// positions). Only differences between two dates are drawn, so the ~0.01°
// residual of the series below never shows at L2 scale.
const A = 1.00000261;
const E = 0.01671123;
const L0 = 100.46457166 * DEG;
const L_RATE = (35999.37244981 / 36525) * DEG;
const PERI0 = 102.93768193 * DEG;
const PERI_RATE = (0.32327364 / 36525) * DEG;

/** Heliocentric ecliptic longitude (rad) and distance (AU) of Earth at `jd`. */
export function earthHeliocentric(jd: number): { lon: number; r: number } {
	const t = jd - J2000;
	const peri = PERI0 + PERI_RATE * t;
	const M = L0 + L_RATE * t - peri;
	const nu = M + (2 * E - E ** 3 / 4) * Math.sin(M) + 1.25 * E * E * Math.sin(2 * M);
	return { lon: peri + nu, r: (A * (1 - E * E)) / (1 + E * Math.cos(nu)) };
}

/** Rewrite an Earth-relative inertial sample taken at `jd` into the frame
 *  co-rotating with the Sun–Earth line as of `jdNow`. Scene axes: ecliptic =
 *  XZ with z = −y_ecl, Y = north. */
export type SampleTransform = (jd: number, v: Float64Array) => void;

export function lagrangeSampleTransform(jdNow: number): SampleTransform {
	const nowLon = earthHeliocentric(jdNow).lon;
	return (jd, v) => {
		const d = nowLon - earthHeliocentric(jd).lon;
		const c = Math.cos(d);
		const s = Math.sin(d);
		const x = v[0];
		const z = v[2];
		v[0] = x * c + z * s;
		v[2] = -x * s + z * c;
	};
}
