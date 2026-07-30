import * as m from '$lib/paraglide/messages.js';
import { getLocale } from '$lib/paraglide/runtime.js';
import { formatUnit } from './quantities';

/** NSSDCA mean sea-level pressure — the same figure the Earth panel shows, so
 *  the comparison and the row it is compared against agree. */
export const EARTH_SEA_LEVEL_PA = 101400;

/**
 * Atmospheric pressures span sixteen orders of magnitude (Venus 9.2 MPa to
 * Mercury's 5·10⁻¹⁰ Pa exosphere), so one unit and one notation cannot serve
 * them all: bar above a kilopascal, where "92 bar" is the figure people know,
 * plain pascals through the thin end, and scientific notation once the zeros
 * stop being countable.
 */
export function formatPressure(pa: number): string {
	if (!Number.isFinite(pa) || pa <= 0) return '';
	if (pa >= 1e3) return `${sig(pa / 1e5, 3)} ${formatUnit('bar', true)}`;
	if (pa >= 1e-2) return `${sig(pa, 3)} ${formatUnit('pascal', true)}`;
	return `${scientific(pa)} ${formatUnit('pascal', true)}`;
}

/**
 * The same pressure against Earth's: a multiple where the body is thicker
 * ("91× Earth's sea-level pressure"), a percentage where it is thinner, since
 * "0.63%" carries more than "0.0063×" and Mercury's 5·10⁻¹³ % carries more
 * than either as a decimal.
 */
export function formatEarthRatio(pa: number): string {
	const ratio = pa / EARTH_SEA_LEVEL_PA;
	if (ratio >= 1) return m.atmosphere_pressure_vs_earth_times({ value: sig(ratio, 3) });
	const percent = ratio * 100;
	return m.atmosphere_pressure_vs_earth_percent({
		value: percent >= 1e-2 ? sig(percent, 2) : scientific(percent)
	});
}

/** Locale-formatted, `digits` significant figures, no trailing zeros. */
function sig(value: number, digits: number): string {
	return new Intl.NumberFormat(getLocale(), { maximumSignificantDigits: digits }).format(value);
}

const SUPERSCRIPTS = '⁰¹²³⁴⁵⁶⁷⁸⁹';

/** "5×10⁻¹⁰" — Intl's own scientific notation renders as "5E-10". */
function scientific(value: number): string {
	const exponent = Math.floor(Math.log10(value));
	const mantissa = value / 10 ** exponent;
	const digits = [...String(Math.abs(exponent))].map((d) => SUPERSCRIPTS[Number(d)]).join('');
	return `${sig(mantissa, 2)}×10${exponent < 0 ? '⁻' : ''}${digits}`;
}
