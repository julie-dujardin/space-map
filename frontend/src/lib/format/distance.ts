import * as m from '$lib/paraglide/messages.js';
import { getLocale } from '$lib/paraglide/runtime.js';
import {
	formatCompactNumber,
	formatQuantity,
	formatUnit,
	joinParts,
	precisionOptions,
	sigFigures,
	type Parts
} from './quantities';
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

/** "84.85 km", or metres under a kilometre — three decimals of a km is "0 km"
 *  for anything smaller, and a layer nobody can read the thickness of may as
 *  well not be drawn. */
export function formatKm(value: number): string {
	if (value !== 0 && Math.abs(value) < 1) {
		return formatQuantity({ value: value * 1000, unit: 'metre' }, true);
	}
	return formatQuantity({ value, unit: 'kilometre' }, true);
}

/** A span too long for a stat box as it stands: "1.97B km". */
export function formatCompactKm(value: number): string {
	return joinParts({ value: formatCompactNumber(value), unit: formatUnit('kilometre', true) });
}

/**
 * "0–2,900 km": the unit said once, the separator the locale's own. Precision
 * follows `formatNumber`, from whichever end is larger. Ends that format alike
 * collapse to one value rather than taking `formatRange`'s "~" approximation.
 */
export function formatKmRange(fromKm: number, toKm: number): string {
	// Both ends in metres or neither: a range whose units disagree end to end
	// reads as two quantities rather than one span. The wider end decides.
	const widest = Math.max(Math.abs(fromKm), Math.abs(toKm));
	const metres = widest !== 0 && widest < 1;
	const [from_, to_] = metres ? [fromKm * 1000, toKm * 1000] : [fromKm, toKm];

	const format = new Intl.NumberFormat(
		getLocale(),
		precisionOptions(metres ? widest * 1000 : widest)
	);
	const unit = formatUnit(metres ? 'metre' : 'kilometre', true);
	const from = format.format(from_);
	if (from === format.format(to_)) return joinParts({ value: from, unit });
	return joinParts({ value: format.formatRange(from_, to_), unit });
}

/** A length under a metre, in µm below 1 mm and in mm above, to `digits`
 *  significant figures. The rounding comes first, so 999.7 µm gives 1 mm. */
export function smallLengthParts(metres: number, digits = 2): Parts {
	const rounded = Number(metres.toPrecision(digits));
	return rounded >= 1e-3
		? { value: sigFigures(rounded * 1e3, digits), unit: m.symbol_millimetre() }
		: { value: sigFigures(rounded * 1e6, digits), unit: m.symbol_micrometre() };
}

/** A length in mm below 1 cm, in cm below 1 m and in m above, to `digits`
 *  significant figures. The rounding comes first, so 99.7 cm gives 1 m. */
export function lengthParts(metres: number, digits = 2): Parts {
	const rounded = Number(metres.toPrecision(digits));
	if (rounded >= 1) return { value: sigFigures(rounded, digits), unit: m.symbol_metre() };
	return rounded >= 1e-2
		? { value: sigFigures(rounded * 1e2, digits), unit: m.symbol_centimetre() }
		: { value: sigFigures(rounded * 1e3, digits), unit: m.symbol_millimetre() };
}
