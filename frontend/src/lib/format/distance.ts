import { getLocale } from '$lib/paraglide/runtime.js';
import { formatQuantity, formatUnit, precisionOptions } from './quantities';
import { AU_KM } from '$lib/math/units';

type DistanceUnit = 'astronomical_unit' | 'kilometre';

const AU_TO_KM_THRESHOLD = 0.01;

function pickUnit(au: number): DistanceUnit {
	const abs = Math.abs(au);
	return abs > 0 && abs < AU_TO_KM_THRESHOLD ? 'kilometre' : 'astronomical_unit';
}

export function convertDistance(au: number): { value: number; unit: DistanceUnit } {
	const unit = pickUnit(au);
	return { value: unit === 'kilometre' ? au * AU_KM : au, unit };
}

export function formatDistance(au: number): string {
	return formatQuantity(convertDistance(au), true);
}

/** "84.85 km". */
export function formatKm(value: number): string {
	return formatQuantity({ value, unit: 'kilometre' }, true);
}

/**
 * "0–2,900 km": the unit said once, the separator the locale's own. Precision
 * follows `formatNumber`, from whichever end is larger. Ends that format alike
 * collapse to one value rather than taking `formatRange`'s "~" approximation.
 */
export function formatKmRange(fromKm: number, toKm: number): string {
	const format = new Intl.NumberFormat(
		getLocale(),
		precisionOptions(Math.max(Math.abs(fromKm), Math.abs(toKm)))
	);
	const unit = formatUnit('kilometre', true);
	const from = format.format(fromKm);
	if (from === format.format(toKm)) return `${from} ${unit}`;
	return `${format.formatRange(fromKm, toKm)} ${unit}`;
}
