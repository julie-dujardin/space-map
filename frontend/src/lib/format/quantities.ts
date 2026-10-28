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

/** Fraction digits that show an uncertainty to two significant figures. With
 *  `roundLarge`, an error of 100 or more rounds to tens or more: a value
 *  scaled into a much smaller unit has no more digits than its fit. */
export function errorDecimals(error: number, roundLarge = false): number {
	if (!(error > 0) || !Number.isFinite(error)) return 2;
	// A float32 0.01 is 0.0099999998: its decade is still the hundredths.
	const decimals = Math.min(8, 1 - Math.floor(Math.log10(error) + 1e-6));
	return roundLarge ? decimals : Math.max(0, decimals);
}

/** A value with exactly this many fraction digits; fewer than none rounds to
 *  tens and more. */
export function fixed(value: number, decimals: number): string {
	const scale = decimals < 0 ? 10 ** -decimals : 1;
	const rounded = decimals < 0 ? Math.round(value / scale) * scale : value;
	const fractionDigits = Math.max(0, decimals);
	return new Intl.NumberFormat(getLocale(), {
		minimumFractionDigits: fractionDigits,
		maximumFractionDigits: fractionDigits
	}).format(rounded);
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

/**
 * One share among several. Two significant digits, except a share that would
 * round up to 100% while others remain, which keeps digits until it stays
 * under: "99.7%" beside "0.35%", never "100%" beside anything.
 */
export function formatShare(fraction: number, alone = false): string {
	if (alone || fraction < 0.995) return formatPercent(fraction);
	for (let digits = 3; digits <= 6; digits++) {
		if (Number((fraction * 100).toPrecision(digits)) < 100) return formatPercent(fraction, digits);
	}
	return formatPercent(fraction, 6);
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

/** The same space for a lower bound. */
export function formatLowerBound(text: string): string {
	return `> ${text}`;
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

export function arcsecondParts(figure: string): Parts {
	return { value: figure, unit: m.symbol_arcsecond(), tight: true };
}

export function formatArcseconds(arcseconds: number): string {
	return joinParts(arcsecondParts(formatNumber(arcseconds)));
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
	return joinParts(quantityParts(q, short_unit));
}

export interface MeasuredQuantity {
	value: number;
	/** Positive errors above and below the value. */
	upperError?: number | null;
	lowerError?: number | null;
	/** A display-ready unit symbol. */
	unit?: string;
	tight?: boolean;
	/** The catalogue value before unit conversion. */
	rawValue?: number;
	maxSignificantDigits?: number;
	/** Caps digits at the precision published by the catalogue. */
	publishedDecimals?: number | null;
	/** Used when no uncertainty is available. */
	fixedDecimals?: number;
	/** Rounds an error of 100 or more to two figures, as `errorDecimals` does
	 *  with `roundLarge`. */
	roundLargeErrors?: boolean;
	/** Writes the figures as multiples of this power of ten: "(8.21 ± 0.41)×10²⁴ kg". */
	power?: number;
	/** Brackets a ± reading, for a factor that follows it: "(1.06 ± 0.06)× Earth". */
	group?: boolean;
}

const SYMMETRIC_ERROR = 0.1;

/** A unit after a power of ten the figures are multiples of: "×10²⁴ kg". The
 *  power binds to the figures; the unit follows it after a space. */
export function powerUnit(unit: string, power: number): Omit<Parts, 'value'> {
	return { unit: joinParts({ value: `×10${superscript(power)}`, unit }), tight: true };
}

function publishedDigits(value: number): number {
	const mantissa = Math.abs(value).toExponential().split('e')[0];
	return Math.max(1, mantissa.replace('.', '').replace(/0+$/, '').length);
}

/** Fraction digits carried by a published decimal. */
export function fractionDigits(value: number): number {
	const [mantissa, exponent] = Math.abs(value).toExponential().split('e');
	const digits = (mantissa.split('.')[1] ?? '').replace(/0+$/, '').length;
	return Math.max(0, digits - Number(exponent));
}

/** A value with symmetric or asymmetric uncertainty, using the normal quantity path. */
export function formatMeasuredQuantity(q: MeasuredQuantity): string {
	const scale = 10 ** -(q.power ?? 0);
	const { unit, tight } =
		q.power === undefined
			? { unit: q.unit ?? '', tight: q.tight }
			: powerUnit(q.unit ?? '', q.power);
	const parts = (value: string) => joinParts({ value, unit, tight });
	const value = q.value * scale;
	const error = (e: number | null | undefined) => (e != null && e > 0 ? e * scale : null);
	const up = error(q.upperError);
	const low = error(q.lowerError);
	if (up === null && low === null) {
		const figure =
			q.fixedDecimals === undefined
				? sigFigures(
						value,
						Math.min(publishedDigits(q.rawValue ?? value), q.maxSignificantDigits ?? 9)
					)
				: fixed(value, q.fixedDecimals);
		return parts(figure);
	}

	const hi = up ?? low!;
	const lo = low ?? up!;
	const half = (hi + lo) / 2;
	const decimals = (error: number) =>
		q.publishedDecimals === null || q.publishedDecimals === undefined
			? errorDecimals(error, q.roundLargeErrors)
			: Math.min(errorDecimals(error), q.publishedDecimals);
	if (Math.abs(hi - lo) <= SYMMETRIC_ERROR * half) {
		const d = decimals(half);
		const figure = fixed(value, d);
		const width = fixed(half, d);
		if (q.power !== undefined || q.group) return ltrIsolate(parts(`(${figure} ±\u00a0${width})`));
		return ltrIsolate(
			tight ? `${parts(figure)} ±\u00a0${parts(width)}` : `${figure} ±\u00a0${parts(width)}`
		);
	}

	return formatValueSpan(value, value - lo, value + hi, decimals(Math.min(hi, lo)), {
		unit,
		tight
	});
}

/** "301 pc (258–360 pc)": a value and the span of its uncertainty. */
export function formatValueSpan(
	value: number,
	from: number,
	to: number,
	decimals: number,
	unit: Omit<Parts, 'value'>
): string {
	const parts = (text: string) => joinParts({ ...unit, value: text });
	// Spaced where an end is negative: "−0.18–−0.17" jams the dash against a sign.
	const separator = from < 0 || to < 0 ? ' – ' : '–';
	const span = `${fixed(from, decimals)}${separator}${fixed(to, decimals)}`;
	return ltrIsolate(`${parts(fixed(value, decimals))} (${parts(span)})`);
}

/** A catalogue quantity at the precision of its published decimals. */
export function formatCatalogueQuantity(
	value: number,
	upperError: number | null,
	lowerError: number | null,
	unit: string,
	tight = false
): string {
	return formatMeasuredQuantity({
		value,
		upperError,
		lowerError,
		unit,
		tight,
		rawValue: value,
		publishedDecimals: Math.max(...[value, upperError ?? 0, lowerError ?? 0].map(fractionDigits))
	});
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

/** The power of ten that leaves `value` one digit before the point at `digits`
 *  significant figures. */
export function powerOfTen(value: number, digits = 2): number {
	const exponent = Math.floor(Math.log10(Math.abs(value)));
	// Rounding the mantissa carries: Pluto's 9.96×10⁸ km³ of water at two
	// figures is "10×10⁸", the right number written the wrong way.
	return Math.abs(Number((value / 10 ** exponent).toPrecision(digits))) >= 10
		? exponent + 1
		: exponent;
}

function superscript(exponent: number): string {
	const digits = [...String(Math.abs(exponent))].map((d) => SUPERSCRIPTS[Number(d)]).join('');
	return `${exponent < 0 ? '⁻' : ''}${digits}`;
}

/** "1.90×10²⁷ kg": three fixed figures on the value's power of ten, for a
 *  quantity whose neighbours run over many of them. Fixed, as Jupiter's "1.9"
 *  beside Earth's "5.97" reads as less known. */
export function scientificParts(value: number, unit: string): Parts {
	return {
		value: formatMeasuredQuantity({ value, power: powerOfTen(value, 3), fixedDecimals: 2 }),
		unit
	};
}

/** "1.7×10⁻⁶" — Intl's own scientific notation renders as "1.7E-6". */
export function scientificNotation(value: number, digits = 2): string {
	const exponent = powerOfTen(value, digits);
	return `${sigFigures(value / 10 ** exponent, digits)}×10${superscript(exponent)}`;
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
	if (atParity(ratio)) return null;
	if (ratio >= 1) return { multiple: ltrIsolate(sigFigures(ratio)) };
	// Under a hundredth of a percent Intl spells out a row of leading zeros, and
	// Mercury's exosphere is 5×10⁻¹³ of Earth's pressure.
	const text = ratio >= 1e-4 ? formatPercent(ratio, 2) : formatTinyPercent(ratio);
	return { percent: ltrIsolate(text) };
}

/** Within rounding of 1, where a comparison says nothing. */
export function atParity(ratio: number): boolean {
	return Math.abs(ratio - 1) < 5e-3;
}

export type EarthRatio = { multiple: string } | { percent: string };

/** The words around a ratio: "{value}× Earth", "{value} of Earth's". */
export interface RatioWords {
	times: (inputs: { value: string }) => string;
	percent: (inputs: { value: string }) => string;
}

const EARTH_WORDS: RatioWords = { times: m.earth_times, percent: m.earth_percent };

/**
 * The wording that goes with it — "14× Earth", "0.63% of Earth's" — against
 * Earth unless another body's words are given. With errors, at their
 * precision: "(1.055 ± 0.055)× Earth", the multiple bracketing its errors as
 * it applies to them too.
 */
export function earthRatio(
	ratio: number,
	{
		words = EARTH_WORDS,
		upperError = null,
		lowerError = null
	}: { words?: RatioWords; upperError?: number | null; lowerError?: number | null } = {}
): string | null {
	const parts = earthRatioParts(ratio);
	if (!parts) return null;
	if (!upperError && !lowerError) {
		return 'multiple' in parts
			? words.times({ value: parts.multiple })
			: words.percent({ value: parts.percent });
	}
	const percent = 'percent' in parts;
	const scale = percent ? 100 : 1;
	const figure = formatMeasuredQuantity({
		value: ratio * scale,
		upperError: upperError && upperError * scale,
		lowerError: lowerError && lowerError * scale,
		roundLargeErrors: true,
		...(percent ? { unit: percentParts(0).unit, tight: true } : { group: true })
	});
	return percent ? words.percent({ value: figure }) : words.times({ value: figure });
}
