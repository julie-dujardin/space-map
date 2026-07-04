import * as m from '$lib/paraglide/messages.js';
import { getLocale } from '$lib/paraglide/runtime.js';

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

export function formatCurrency(q: { value: number; currency: string }): string {
	return new Intl.NumberFormat(getLocale(), {
		style: 'currency',
		currency: q.currency
	}).format(q.value);
}
