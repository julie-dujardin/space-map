/**
 * Mars seasonal atmosphere: solar longitude L_s (Allison & McEwen 2000, ~0.05°)
 * drives the exported climatology table — dust column, dust scale height,
 * CO₂ condensation pressure. A cheap param rewrite, so it runs on every tier.
 */

import type { AtmosphereParams } from './atmosphere';

const DEG = Math.PI / 180;
const J2000_JD = 2451545.0;

/** Mars areocentric solar longitude, degrees in [0, 360). `jd` is a UTC
 *  Julian date — the ~69 s TT offset moves L_s by ~4e-4°, far below use. */
export function marsSolarLongitudeDeg(jd: number): number {
	const d = jd - J2000_JD;
	const m = (19.3871 + 0.52402073 * d) * DEG;
	const alphaFMS = 270.3871 + 0.524038496 * d;
	const nuMinusM =
		(10.691 + 3.0e-7 * d) * Math.sin(m) +
		0.623 * Math.sin(2 * m) +
		0.05 * Math.sin(3 * m) +
		0.005 * Math.sin(4 * m) +
		0.0005 * Math.sin(5 * m);
	return (((alphaFMS + nuMinusM) % 360) + 360) % 360;
}

/** Piecewise-linear sample of a seasonal factor row at `lsDeg`, wrapping
 *  330→360|0. The grid is sorted and starts at 0. */
function sampleSeason(lsGrid: readonly number[], values: readonly number[], lsDeg: number): number {
	const n = lsGrid.length;
	let i = n - 1;
	for (let k = 0; k < n - 1; k++) {
		if (lsDeg < lsGrid[k + 1]) {
			i = k;
			break;
		}
	}
	const next = (i + 1) % n;
	const span = i === n - 1 ? 360 - lsGrid[i] : lsGrid[next] - lsGrid[i];
	const t = (lsDeg - lsGrid[i]) / span;
	return values[i] + (values[next] - values[i]) * t;
}

/**
 * Base params rewritten for the season at `lsDeg`. Dust β scales by
 * τ_factor · H_base/H_season to keep τ = β·H exact under the scale-height
 * change; pressure scales Rayleigh β alone (isothermal, H unchanged).
 */
export function seasonalAtmosphereParams(base: AtmosphereParams, lsDeg: number): AtmosphereParams {
	const s = base.seasonal;
	if (!s) return base;
	const tauF = sampleSeason(s.lsDeg, s.dustTauFactor, lsDeg);
	const dustH = sampleSeason(s.lsDeg, s.dustScaleHeightKm, lsDeg);
	const pressureF = sampleSeason(s.lsDeg, s.pressureFactor, lsDeg);
	const mieF = (tauF * base.mieScaleHeightKm) / dustH;
	const scale3 = (v: [number, number, number], f: number): [number, number, number] => [
		v[0] * f,
		v[1] * f,
		v[2] * f
	];
	return {
		...base,
		rayleighScatterPerKm: scale3(base.rayleighScatterPerKm, pressureF),
		mieScatterPerKm: scale3(base.mieScatterPerKm, mieF),
		mieAbsorptionPerKm: scale3(base.mieAbsorptionPerKm, mieF),
		mieScaleHeightKm: dustH,
		seasonal: undefined
	};
}

interface SeasonCacheEntry {
	lsQ: number;
	params: AtmosphereParams;
}

// One derived-param object per base, reused until L_s drifts past the
// quantum — keeps updateAtmosphereShaders' identity check (and the uniform
// rewrites behind it) from firing every frame.
const cache = new WeakMap<AtmosphereParams, SeasonCacheEntry>();

/** ~0.25° of L_s ≈ half a Mars day — far under a visible factor change. */
const LS_QUANTUM_DEG = 0.25;

/** Cached seasonal derivation for the sim clock's `jd`; returns `base` itself
 *  for bodies without a seasonal table. */
export function seasonalParamsForJd(base: AtmosphereParams, jd: number): AtmosphereParams {
	if (!base.seasonal) return base;
	const lsQ = Math.round(marsSolarLongitudeDeg(jd) / LS_QUANTUM_DEG);
	const hit = cache.get(base);
	if (hit && hit.lsQ === lsQ) return hit.params;
	const params = seasonalAtmosphereParams(base, lsQ * LS_QUANTUM_DEG);
	cache.set(base, { lsQ, params });
	return params;
}
