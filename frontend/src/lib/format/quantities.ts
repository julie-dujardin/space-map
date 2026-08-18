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

/**
 * A figure and the unit it is quoted in, kept apart.
 *
 * Two things need the split: a stat tile that sets the unit in its own type,
 * and a span that says the unit once. `unit` is empty for a bare count.
 *
 * A unit is always a symbol standing alone, never a message with the figure
 * baked into it. A "{value} kg/s" message can only wrap a string that is
 * already finished, so a range comes out "200 (170–230) kg/s" beside a
 * prefixed unit's "15.8 GW (12.7–18.9 GW)" — the same reading punctuated two
 * ways, which is how the two forms drifted apart in the first place.
 */
export interface Parts {
	value: string;
	unit: string;
	/** Degrees and their like bind to the digits with no space between. */
	tight?: boolean;
}

/** How a quantity of one kind picks its unit — watts to terawatts, pascals to
 *  bar. The argument is the raw SI figure. */
export type PartsOf = (value: number) => Parts;

/** "15.8 GW", "4°", "1,196" — the pair as one string. */
export function joinParts(parts: Parts): string {
	if (!parts.unit) return parts.value;
	return parts.tight ? `${parts.value}${parts.unit}` : `${parts.value} ${parts.unit}`;
}

/**
 * Two readings as one span, low end first.
 *
 * The unit is said once where both ends carry the same one, and twice where
 * they do not: Earth's stratosphere runs 0.226 bar to 66.9 Pa, and one unit
 * across that is off by four orders of magnitude. The wider form takes the
 * wider separator, so "250 Ma – 1 Ga" doesn't read as one hyphenated quantity.
 */
export function formatSpan(low: Parts, high: Parts): string {
	if (low.unit === high.unit && low.tight === high.tight) {
		return joinParts({ ...high, value: `${low.value}–${high.value}` });
	}
	return `${joinParts(low)} – ${joinParts(high)}`;
}

/**
 * The same span for a message that sets its own separator — "{low}–{high}".
 *
 * A few spans are written inside a sentence a translator owns, and the
 * separator is part of that sentence: Japanese writes 24〜57 where the others
 * write 24–57. The message keeps the punctuation and this keeps the rule about
 * the unit, which is the half that kept coming out different per call site.
 */
export function spanFields(low: Parts, high: Parts): { low: string; high: string } {
	const once = low.unit === high.unit && low.tight === high.tight;
	return { low: once ? low.value : joinParts(low), high: joinParts(high) };
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

/**
 * A percentage split from its sign, so a span can say the sign once.
 *
 * The sign carries whatever the locale sets around it — French's no-break
 * space, Arabic's marks — so the pair still joins back to exactly what Intl
 * wrote. A locale that leads with the sign has nothing to split off and keeps
 * the whole reading as its figure.
 */
export function percentParts(fraction: number, significantDigits = 2): Parts {
	const parts = new Intl.NumberFormat(getLocale(), {
		style: 'percent',
		maximumSignificantDigits: significantDigits
	}).formatToParts(fraction);
	const text = (from: number, to?: number) =>
		parts
			.slice(from, to)
			.map((p) => p.value)
			.join('');

	const sign = parts.findIndex((p) => p.type === 'percentSign');
	if (sign <= 0) return { value: text(0), unit: '' };
	// The space before the sign belongs to the sign, not to the digits.
	let cut = sign;
	while (cut > 0 && parts[cut - 1].type === 'literal') cut--;
	return { value: text(0, cut), unit: text(cut), tight: true };
}

/** "12%", from a 0–1 fraction. */
export function formatPercent(fraction: number, significantDigits = 2): string {
	return joinParts(percentParts(fraction, significantDigits));
}

/** The locale's percent sign on a figure the caller wrote — a chart's share
 *  picks its own digits where `percentParts` takes Intl's. */
export function asPercent(figure: string): Parts {
	return { ...percentParts(0), value: figure };
}

/**
 * A percentage too small to write plainly — Venus's added cancer risk is
 * 0.0000000036%, which nobody can take a size from.
 */
export function formatTinyPercent(fraction: number): string {
	return joinParts(asPercent(scientificNotation(fraction * 100)));
}

/**
 * A non-detection: "< 0.78 nT".
 *
 * The space is what separates a bound from a quantity that happens to start
 * with a sign, and it is the same space in every panel that has one.
 */
export function formatBound(text: string): string {
	return `< ${text}`;
}

/**
 * An angle. The sign binds to the digits, and the figure is the caller's: a
 * published measurement keeps its own digits where a stat cell rounds.
 */
export function angleParts(figure: string): Parts {
	return { value: figure, unit: m.symbol_degree(), tight: true };
}

/** "23.4°" — an angle at the precision the panels read at. */
export function formatDegrees(degrees: number): string {
	return joinParts(angleParts(formatNumber(degrees)));
}

/** Locale-aware compact notation ("1.34M"), ~3 significant digits. */
export function formatCompactNumber(n: number): string {
	if (!Number.isFinite(n)) return String(n);
	return new Intl.NumberFormat(getLocale(), {
		notation: 'compact',
		maximumSignificantDigits: 3
	}).format(n);
}

/** An exported quantity as a figure and its label, for spans and stat tiles. */
export function quantityParts(q: { value: number; unit: string }, short_unit?: boolean): Parts {
	return { value: formatNumber(q.value), unit: formatUnit(q.unit, short_unit) };
}

export function formatQuantity(q: { value: number; unit: string }, short_unit?: boolean): string {
	const plural = short_unit ? undefined : PLURAL_UNIT_NAMES[q.unit];
	// The inflected names read as one phrase and cannot be split in two.
	if (plural) return plural({ count: q.value, display: formatNumber(q.value) });
	return joinParts(quantityParts(q, short_unit));
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

/** "$148M" — a price whose last six digits are noise beside what it buys. */
export function formatCompactCurrency(q: { value: number; currency: string }): string {
	return new Intl.NumberFormat(getLocale(), {
		style: 'currency',
		currency: q.currency,
		notation: 'compact',
		maximumSignificantDigits: 3
	}).format(q.value);
}

/** Locale-formatted to `digits` significant figures, no trailing zeros. */
export function sigFigures(value: number, digits = 3): string {
	return new Intl.NumberFormat(getLocale(), { maximumSignificantDigits: digits }).format(value);
}

const SUPERSCRIPTS = '⁰¹²³⁴⁵⁶⁷⁸⁹';

/** "1.7×10⁻⁶" — Intl's own scientific notation renders as "1.7E-6". */
export function scientificNotation(value: number, digits = 2): string {
	let exponent = Math.floor(Math.log10(Math.abs(value)));
	// Rounding the mantissa carries: Pluto's 9.96×10⁸ km³ of water at two
	// figures is "10×10⁸", the right number written the wrong way.
	if (Math.abs(Number((value / 10 ** exponent).toPrecision(digits))) >= 10) exponent += 1;
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
	const text = ratio >= 1e-4 ? formatPercent(ratio, 2) : formatTinyPercent(ratio);
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
