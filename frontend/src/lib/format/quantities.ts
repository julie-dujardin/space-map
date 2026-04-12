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

export function formatQuantity(q: { value: number; unit: string }, short_unit?: boolean): string {
	return `${formatNumber(q.value)} ${formatUnit(q.unit, short_unit)}`;
}

export function formatCurrency(q: { value: number; currency: string }): string {
	return new Intl.NumberFormat(getLocale(), {
		style: 'currency',
		currency: q.currency
	}).format(q.value);
}
