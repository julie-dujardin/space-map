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
import { formatPercent, scientificNotation, sigFigures } from './quantities';

/** SI prefixes are the same in every language, so they are built here rather
 *  than carried as twelve copies of "m". */
const PREFIXES: readonly (readonly [number, string])[] = [
	[1, ''],
	[1e-3, 'm'],
	[1e-6, 'µ'],
	[1e-9, 'n'],
	[1e-12, 'p']
];

/** A dose in sieverts, prefixed so the mantissa stays readable. */
export function formatSieverts(sv: number): string {
	if (!Number.isFinite(sv) || sv <= 0) return '';
	const [scale, prefix] = PREFIXES.find(([step]) => sv >= step) ?? PREFIXES[PREFIXES.length - 1];
	return `${sigFigures(sv / scale, 3)} ${prefix}Sv`;
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
