import * as m from '$lib/paraglide/messages.js';
import { getLocale } from '$lib/paraglide/runtime.js';

export function ucfirst(s: string): string {
	return s.charAt(0).toUpperCase() + s.slice(1);
}

export function formatUnit(unit: string, short?: boolean): string {
	const symbolKey = short ? `unit_symbol_${unit}` : `unit_name_${unit}`;
	const fn = (m as unknown as Record<string, (() => string) | undefined>)[symbolKey];
	return fn ? fn() : unit.replace(/_/g, ' ');
}

export function formatNumber(n: number): string {
	if (!Number.isFinite(n)) return String(n);
	const intDigits = Math.floor(Math.abs(n)) === 0 ? 0 : Math.floor(Math.log10(Math.abs(n))) + 1;
	const fracDigits = Math.max(0, 3 - intDigits);
	const rounded = fracDigits === 0 ? Math.round(n) : parseFloat(n.toFixed(fracDigits));
	return rounded.toLocaleString(getLocale());
}

export function formatQuantity(q: { value: number; unit: string }, short_unit?: boolean): string {
	return `${formatNumber(q.value)} ${formatUnit(q.unit, short_unit)}`;
}
