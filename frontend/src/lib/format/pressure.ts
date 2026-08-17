import * as m from '$lib/paraglide/messages.js';
import {
	earthRatio,
	formatSpan,
	formatUnit,
	joinParts,
	scientificNotation,
	sigFigures,
	type Parts
} from './quantities';

/** NSSDCA mean sea-level pressure — the same figure the Earth panel shows, so
 *  the comparison and the row it is compared against agree. */
export const EARTH_SEA_LEVEL_PA = 101400;

/** What the figure is quoted at, which is part of the claim: Saturn's is a
 *  cloud deck and Mars's is a datum surface nobody could stand on. */
const LEVEL_LABEL: Record<string, () => string> = {
	surface: m.atmosphere_pressure_surface,
	sea_level: m.atmosphere_pressure_sea_level,
	areoid: m.atmosphere_pressure_areoid,
	cloud_top: m.atmosphere_pressure_cloud_top,
	one_bar: m.atmosphere_pressure_one_bar,
	photosphere: m.atmosphere_pressure_photosphere
};

export function pressureLevelLabel(level: string): string {
	return (LEVEL_LABEL[level] ?? LEVEL_LABEL.surface)();
}

/**
 * Atmospheric pressures span sixteen orders of magnitude (Venus 9.2 MPa to
 * Mercury's 5·10⁻¹⁰ Pa exosphere), so one unit and one notation cannot serve
 * them all: bar above a kilopascal, where "92 bar" is the figure people know,
 * plain pascals through the thin end, and scientific notation once the zeros
 * stop being countable.
 */
export function formatPressure(pa: number): string {
	const parts = pressureParts(pa);
	return parts ? joinParts(parts) : '';
}

/** The number and its unit apart, so a span can say the unit once. Null where
 *  there is no pressure to quote — the shared `PartsOf` has no such case. */
function pressureParts(pa: number): Parts | null {
	if (!Number.isFinite(pa) || pa <= 0) return null;
	if (pa >= 1e3) return { value: sigFigures(pa / 1e5, 3), unit: formatUnit('bar', true) };
	const value = pa >= 1e-2 ? sigFigures(pa, 3) : scientificNotation(pa);
	return { value, unit: formatUnit('pascal', true) };
}

/**
 * The two ends of a layer, bottom first — the pressure counterpart of
 * `formatTemperatureSpan`.
 *
 * Each end carries its own unit wherever they differ, which across a layer they
 * usually do: Earth's stratosphere runs from 0.226 bar to 66.9 Pa, and saying
 * the unit once would be off by four orders of magnitude.
 */
export function formatPressureSpan(bottomPa: number, topPa: number): string {
	const a = pressureParts(bottomPa);
	const b = pressureParts(topPa);
	if (!a || !b) return formatPressure(bottomPa) || formatPressure(topPa);
	// Ends that round to the same figure are one reading, not a span of it.
	if (a.value === b.value && a.unit === b.unit) return joinParts(a);
	return formatSpan(a, b);
}

/** This pressure against the one everybody stands in, by the shared rule. Null
 *  on Earth itself, which is the only body it says nothing about. */
export function formatEarthRatio(pa: number): string | null {
	return earthRatio(pa / EARTH_SEA_LEVEL_PA);
}
