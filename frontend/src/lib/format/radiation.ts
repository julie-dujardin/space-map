/**
 * Reading a dose rate out loud, and saying what it would do to somebody.
 *
 * Two things make this awkward. The rates span fifteen orders of magnitude —
 * Venus's surface at 2 pSv/day against Europa's at a thousand Sv/day — so no
 * single prefix serves them. And the two ends are not the same quantity in any
 * useful sense: a few mSv/day is a lifetime cancer risk accumulated over years,
 * a thousand Sv/day is an injury delivered in minutes, and the sentence that
 * makes one legible makes the other absurd. So the derived reading follows the
 * environment's `kind` rather than the size of the number.
 */

import * as m from '$lib/paraglide/messages.js';
import { CANCER_RISK_PER_SV, LETHAL_DOSE_GY } from '$lib/math/travel';
import { formatDuration } from './duration';
import { formatPercent, joinParts, scientificNotation, sigFigures, type Parts } from './quantities';

// One symbol per prefixed sievert rather than a Latin prefix glued onto a
// translated unit: Russian writes the sievert Зв, and concatenation produced
// "мSv" here while the travel panel said "мЗв" for the same dose.
const SIEVERTS: readonly (readonly [number, () => string])[] = [
	[1, m.symbol_sievert],
	[1e-3, m.symbol_millisievert],
	[1e-6, m.symbol_microsievert],
	[1e-9, m.symbol_nanosievert],
	[1e-12, m.symbol_picosievert]
];

/**
 * A dose in whichever sievert keeps the mantissa readable, from Venus's 2
 * pSv/day to Europa's thousand Sv/day.
 *
 * `figure` is the caller's own rounding, which is the one thing the two
 * readers disagree on: an environment is quoted to three significant figures
 * and a trip total to two, because the models behind them are known that far.
 */
export function sievertParts(sv: number, figure: (value: number) => string): Parts {
	const [scale, unit] = SIEVERTS.find(([step]) => sv >= step) ?? SIEVERTS[SIEVERTS.length - 1];
	return { value: figure(sv / scale), unit: unit() };
}

/** A dose in sieverts, prefixed so the mantissa stays readable. */
export function formatSieverts(sv: number): string {
	if (!Number.isFinite(sv) || sv <= 0) return '';
	return joinParts(sievertParts(sv, (value) => sigFigures(value, 3)));
}

/** The same, as the rate it actually is. */
export function formatDoseRate(svPerDay: number): string {
	const dose = formatSieverts(svPerDay);
	return dose ? m.radiation_per_day({ dose }) : '';
}

const DAYS_PER_YEAR = 365.25;

/**
 * What a year of it comes to, as added lifetime cancer risk. ICRP's coefficient
 * is linear, which is extrapolation above roughly 1 Sv — but a body a person
 * could stand on never gets near that in a year, and the ones that do are
 * `trapped` and take the sentence below instead.
 *
 * Below a ten-thousandth of a percent it switches to scientific notation, the
 * same move `earthRatioParts` makes two decades earlier: Venus's year reads
 * "0.0000000036%" written plainly, which nobody can take a size from. The
 * threshold sits lower here because Earth's own 0.0016% is still legible and
 * is the figure every other one is judged against.
 */
export function cancerRiskPerYear(svPerDay: number): string {
	const risk = svPerDay * DAYS_PER_YEAR * CANCER_RISK_PER_SV;
	return risk >= 1e-6 ? formatPercent(risk) : `${scientificNotation(risk * 100)}%`;
}

/**
 * How long a median lethal dose takes. Only for `trapped` environments: the
 * flux there is electrons, whose quality factor is one, so the sievert figure
 * and the gray it is compared against are the same number. Saying this about a
 * cosmic-ray surface would be wrong twice — the dose is heavy ions, and a
 * stochastic risk spread over decades is not an acute injury.
 */
export function timeToLethalDose(svPerDay: number): string {
	return formatDuration(LETHAL_DOSE_GY / svPerDay);
}
