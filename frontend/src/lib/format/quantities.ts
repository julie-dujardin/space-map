import * as m from '$lib/paraglide/messages.js';
import { getLocale } from '$lib/paraglide/runtime.js';
import { ltrIsolate } from './bidi';

export function ucfirst(s: string): string {
	return s.charAt(0).toUpperCase() + s.slice(1);
}

export function formatUnit(unit: string, short?: boolean): string {
	const symbolKey = short ? `unit_symbol_${unit}` : `unit_name_${unit}`;
	const fn = (m as unknown as Record<string, (() => string) | undefined>)[symbolKey];
	if (!fn) {
		console.warn(`Missing unit label: ${symbolKey}`);
		return unit.replace(/_/g, ' ');
	}
	return fn();
}

// Units whose long name inflects with the value (locale-aware plural, e.g.
// "1 Earth mass" vs "2 Earth masses"). Others keep the invariant unit_name_*
// label. Symbols never pluralize.
type PluralName = (i: { count: number; display: string }) => string;
const PLURAL_UNIT_NAMES: Record<string, PluralName> = {
	earth_mass: m.unit_earth_mass_count,
	jupiter_mass: m.unit_jupiter_mass_count
};

/** Intl rounding options that keep ~3 digits of precision (4+ digit integers unchanged). */
export function precisionOptions(
	n: number
): Pick<Intl.NumberFormatOptions, 'maximumFractionDigits'> {
	const intDigits = Math.floor(Math.abs(n)) === 0 ? 0 : Math.floor(Math.log10(Math.abs(n))) + 1;
	return { maximumFractionDigits: Math.max(0, 3 - intDigits) };
}

export function formatNumber(n: number): string {
	if (!Number.isFinite(n)) return String(n);
	return n.toLocaleString(getLocale(), precisionOptions(n));
}

/** "12%", from a 0–1 fraction. */
export function formatPercent(fraction: number, significantDigits = 2): string {
	return new Intl.NumberFormat(getLocale(), {
		style: 'percent',
		maximumSignificantDigits: significantDigits
	}).format(fraction);
}

/** Locale-aware compact notation ("1.34M"), ~3 significant digits. */
export function formatCompactNumber(n: number): string {
	if (!Number.isFinite(n)) return String(n);
	return new Intl.NumberFormat(getLocale(), {
		notation: 'compact',
		maximumSignificantDigits: 3
	}).format(n);
}

export function formatQuantity(q: { value: number; unit: string }, short_unit?: boolean): string {
	const display = formatNumber(q.value);
	const plural = short_unit ? undefined : PLURAL_UNIT_NAMES[q.unit];
	if (plural) return plural({ count: q.value, display });
	return `${display} ${formatUnit(q.unit, short_unit)}`;
}

/** Density in g/cm³, whichever unit Wikidata stored it in.
 *
 * The claims come through unnormalized, so neighbouring bodies read "0.85
 * gram per cubic centimetre" and "850 kilogram per cubic metre" for the same
 * physical density. g/cm³ wins: water is 1, so the number says rock or ice at
 * a glance. */
export function formatDensity(q: { value: number; unit: string }): string {
	const grams =
		q.unit === 'kilogram_per_cubic_metre'
			? { value: q.value / 1000, unit: 'gram_per_cubic_centimetre' }
			: q;
	return formatQuantity(grams);
}

export function formatCurrency(q: { value: number; currency: string }): string {
	return new Intl.NumberFormat(getLocale(), {
		style: 'currency',
		currency: q.currency
	}).format(q.value);
}

/** Locale-formatted to `digits` significant figures, no trailing zeros. */
export function sigFigures(value: number, digits = 3): string {
	return new Intl.NumberFormat(getLocale(), { maximumSignificantDigits: digits }).format(value);
}

const SUPERSCRIPTS = '⁰¹²³⁴⁵⁶⁷⁸⁹';

/** "1.7×10⁻⁶" — Intl's own scientific notation renders as "1.7E-6". */
export function scientificNotation(value: number, digits = 2): string {
	const exponent = Math.floor(Math.log10(value));
	const mantissa = value / 10 ** exponent;
	const superscript = [...String(Math.abs(exponent))].map((d) => SUPERSCRIPTS[Number(d)]).join('');
	return `${sigFigures(mantissa, digits)}×10${exponent < 0 ? '⁻' : ''}${superscript}`;
}

/**
 * How anything reads against Earth's, and the only ruler most of these
 * quantities have: **a multiple at or above parity, a percentage below it**.
 *
 * One rule for every field rather than a choice per call site. Above parity a
 * percentage stops helping ("9,070% of Earth's" for Venus); below it a bare
 * fraction is the harder read, and "1.1×10⁻⁵× Earth" puts two multiplication
 * signs in one string doing different jobs.
 *
 * Null at parity — Earth learns nothing from being compared with itself, and
 * the tolerance is there because it never lands on exactly 1: its own mass is
 * quoted 5.972×10²⁴ kg against the 5.9722×10²⁴ the ratio divides by, which
 * printed "1× Earth".
 */
export function earthRatioParts(ratio: number): EarthRatio | null {
	if (Math.abs(ratio - 1) < 5e-3) return null;
	if (ratio >= 1) return { multiple: ltrIsolate(sigFigures(ratio)) };
	// Under a hundredth of a percent Intl spells out a row of leading zeros, and
	// Mercury's exosphere is 5×10⁻¹³ of Earth's pressure.
	const text = ratio >= 1e-4 ? formatPercent(ratio, 2) : `${scientificNotation(ratio * 100)}%`;
	return { percent: ltrIsolate(text) };
}

export type EarthRatio = { multiple: string } | { percent: string };

/** The wording that goes with it — "14× Earth", "0.63% of Earth's". */
export function earthRatio(ratio: number): string | null {
	const parts = earthRatioParts(ratio);
	if (!parts) return null;
	return 'multiple' in parts
		? m.earth_times({ value: parts.multiple })
		: m.earth_percent({ value: parts.percent });
}
