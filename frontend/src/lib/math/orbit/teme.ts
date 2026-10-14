/**
 * TEME of date → ecliptic J2000.
 *
 * SGP4 gives positions in TEME: the true equator of the date and a mean
 * equinox. The rotation to J2000 is the IAU 1976 precession and the IAU 1980
 * nutation that define TEME (Vallado et al. 2006, "Revisiting Spacetrack
 * Report #3"). The nutation series keeps its 18 largest terms. The terms it
 * drops sum to less than 0.1″, which is 20 m at geostationary distance.
 */

import { EARTH_OBLIQUITY_DEG } from '$lib/math/units';
import { J2000_JD } from '$lib/time/jd';

type Mat3 = [number, number, number, number, number, number, number, number, number];

const DEG = Math.PI / 180;
const ARCSEC = DEG / 3600;
/** Unit of the nutation table, 0.0001″. */
const NUT_UNIT = 1e-4 * ARCSEC;
/** The matrix moves by less than 0.003″ in this time, under a metre at geostationary distance. */
const REUSE_DAYS = 0.01;

/** IAU 1980 nutation: multipliers of l, l′, F, D, Ω; then Δψ = (a + b·T)·sin and
 *  Δε = (c + d·T)·cos of the argument, in 0.0001″. */
const NUTATION: readonly (readonly number[])[] = [
	[0, 0, 0, 0, 1, -171996, -174.2, 92025, 8.9],
	[0, 0, 2, -2, 2, -13187, -1.6, 5736, -3.1],
	[0, 0, 2, 0, 2, -2274, -0.2, 977, -0.5],
	[0, 0, 0, 0, 2, 2062, 0.2, -895, 0.5],
	[0, 1, 0, 0, 0, 1426, -3.4, 54, -0.1],
	[1, 0, 0, 0, 0, 712, 0.1, -7, 0],
	[0, 1, 2, -2, 2, -517, 1.2, 224, -0.6],
	[0, 0, 2, 0, 1, -386, -0.4, 200, 0],
	[1, 0, 2, 0, 2, -301, 0, 129, -0.1],
	[0, -1, 2, -2, 2, 217, -0.5, -95, 0.3],
	[1, 0, 0, -2, 0, -158, 0, -1, 0],
	[0, 0, 2, -2, 1, 129, 0.1, -70, 0],
	[-1, 0, 2, 0, 2, 123, 0, -53, 0],
	[1, 0, 0, 0, 1, 63, 0.1, -33, 0],
	[0, 0, 0, 2, 0, 63, 0, -2, 0],
	[-1, 0, 2, 2, 2, -59, 0, 26, 0],
	[-1, 0, 0, 0, 1, -58, -0.1, 32, 0],
	[1, 0, 2, 0, 1, -51, 0, 27, 0]
];

function mul(a: Mat3, b: Mat3): Mat3 {
	const out = new Array(9) as Mat3;
	for (let r = 0; r < 3; r++) {
		for (let c = 0; c < 3; c++) {
			out[3 * r + c] = a[3 * r] * b[c] + a[3 * r + 1] * b[3 + c] + a[3 * r + 2] * b[6 + c];
		}
	}
	return out;
}

/** Frame rotations about X, Y and Z by `a` radians. */
function rx(a: number): Mat3 {
	const c = Math.cos(a);
	const s = Math.sin(a);
	return [1, 0, 0, 0, c, s, 0, -s, c];
}

function ry(a: number): Mat3 {
	const c = Math.cos(a);
	const s = Math.sin(a);
	return [c, 0, -s, 0, 1, 0, s, 0, c];
}

function rz(a: number): Mat3 {
	const c = Math.cos(a);
	const s = Math.sin(a);
	return [c, s, 0, -s, c, 0, 0, 0, 1];
}

/** The rotation at `jd`, row-major: `r_ecliptic = M · r_teme`. */
function temeToEclipticAt(jd: number): Mat3 {
	const T = (jd - J2000_JD) / 36525;

	// IAU 1976 precession angles.
	const zeta = (2306.2181 * T + 0.30188 * T * T + 0.017998 * T ** 3) * ARCSEC;
	const theta = (2004.3109 * T - 0.42665 * T * T - 0.041833 * T ** 3) * ARCSEC;
	const z = (2306.2181 * T + 1.09468 * T * T + 0.018203 * T ** 3) * ARCSEC;

	// IAU 1980 fundamental arguments, degrees.
	const l = 134.96298139 + 477198.8673981 * T + 0.0086972 * T * T;
	const lp = 357.52772333 + 35999.05034 * T - 0.0001603 * T * T;
	const F = 93.27191028 + 483202.0175381 * T - 0.0036825 * T * T;
	const D = 297.85036306 + 445267.11148 * T - 0.0019142 * T * T;
	const om = 125.04452222 - 1934.1362608 * T + 0.0020708 * T * T;

	let dpsi = 0;
	let deps = 0;
	for (const [kl, klp, kF, kD, kOm, a, b, c, d] of NUTATION) {
		const arg = (kl * l + klp * lp + kF * F + kD * D + kOm * om) * DEG;
		dpsi += (a + b * T) * Math.sin(arg);
		deps += (c + d * T) * Math.cos(arg);
	}
	dpsi *= NUT_UNIT;
	deps *= NUT_UNIT;

	const epsMean = (84381.448 - 46.815 * T - 0.00059 * T * T + 0.001813 * T ** 3) * ARCSEC;
	const eqEquinoxes = dpsi * Math.cos(epsMean);

	// r_J2000 = Pᵀ · Nᵀ · R3(−Eq) · r_TEME, then J2000 equator → ecliptic.
	const precessionT = mul(mul(rz(zeta), ry(-theta)), rz(z));
	const nutationT = mul(mul(rx(-epsMean), rz(dpsi)), rx(epsMean + deps));
	const toJ2000 = mul(mul(precessionT, nutationT), rz(-eqEquinoxes));
	return mul(rx(EARTH_OBLIQUITY_DEG * DEG), toJ2000);
}

let cachedJd = NaN;
let cached: Mat3 = [1, 0, 0, 0, 1, 0, 0, 0, 1];

/** TEME → ecliptic J2000 rotation at `jd` (UTC is close enough), row-major. */
export function temeToEclipticMatrix(jd: number): Mat3 {
	if (!(Math.abs(jd - cachedJd) <= REUSE_DAYS)) {
		cached = temeToEclipticAt(jd);
		cachedJd = jd;
	}
	return cached;
}

/** A TEME vector at `jd` in ecliptic J2000, same units. */
export function temeToEcliptic(
	x: number,
	y: number,
	z: number,
	jd: number
): [number, number, number] {
	const m = temeToEclipticMatrix(jd);
	return [
		m[0] * x + m[1] * y + m[2] * z,
		m[3] * x + m[4] * y + m[5] * z,
		m[6] * x + m[7] * y + m[8] * z
	];
}
