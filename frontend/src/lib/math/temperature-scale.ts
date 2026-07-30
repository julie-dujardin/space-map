/**
 * Positions a body's temperature on a scale shared by every body, so a reading
 * is legible as "cold/warm/hot for the solar system" and not just a number.
 *
 * Two regimes rather than one axis: planets and stars are four orders of
 * magnitude apart, and warping a single axis to fit both would flatten the
 * whole planetary range into a sliver. All maths is in kelvin — °C goes
 * negative, which the stellar log segment cannot take.
 */

export type TemperatureRegime = 'planetary' | 'stellar';

/**
 * Absolute zero to a round ceiling above Venus (737 K), the hottest surface we
 * carry. Fixed rather than data-derived so the axis doesn't shift under a
 * Wikidata refresh, and so nothing sits exactly on an end.
 */
const PLANETARY_DOMAIN: readonly [number, number] = [0, 1000];

/** Five decades, log: M-dwarf photospheres through the hottest stellar cores. */
const STELLAR_DOMAIN: readonly [number, number] = [1e3, 1e8];

/** Liquid water at 1 atm — the goldilocks band marked on the planetary scale. */
export const HABITABLE_RANGE_K: readonly [number, number] = [273.15, 373.15];

/** Colour ramps declared in kelvin so the stops track the physics, not the pixels. */
const PLANETARY_STOPS: readonly (readonly [number, string])[] = [
	[0, '#1e3a8a'],
	[140, '#0284c7'],
	[HABITABLE_RANGE_K[0], '#22c55e'],
	[HABITABLE_RANGE_K[1], '#22c55e'],
	[560, '#eab308'],
	[760, '#f97316'],
	[1000, '#b91c1c']
];

/**
 * Blackbody colour (Planck → CIE 1931 → sRGB, normalised to constant
 * brightness). Saturates to blue-white past ~40 kK, which is the real
 * behaviour: hotter emitters do not look any bluer to the eye.
 */
const STELLAR_STOPS: readonly (readonly [number, string])[] = [
	[1000, '#ff2f00'],
	[1500, '#ff6a00'],
	[2000, '#ff8d15'],
	[3000, '#ffb96e'],
	[4000, '#ffd4a6'],
	[5000, '#ffe7d0'],
	[5772, '#fff1ea'],
	[6500, '#fff9fe'],
	[8000, '#e3e7ff'],
	[10000, '#cdd9ff'],
	[15000, '#b5c9ff'],
	[20000, '#abc1ff'],
	[30000, '#a2bbff'],
	[40000, '#9eb8ff'],
	[1e5, '#98b3ff'],
	[1e8, '#95b1ff']
];

/** The regime a set of readings belongs to; stellar once past the planetary ceiling. */
export function regimeFor(kelvins: number[]): TemperatureRegime {
	return kelvins.some((k) => k > PLANETARY_DOMAIN[1]) ? 'stellar' : 'planetary';
}

/** Fractional position (0–1) of a reading on its regime's axis, clamped to the ends. */
export function scalePosition(kelvin: number, regime: TemperatureRegime): number {
	const [lo, hi] = regime === 'stellar' ? STELLAR_DOMAIN : PLANETARY_DOMAIN;
	const t =
		regime === 'stellar'
			? (Math.log10(Math.max(kelvin, lo)) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))
			: (kelvin - lo) / (hi - lo);
	return Math.min(1, Math.max(0, t));
}

export interface GradientStop {
	/** Fractional position along the bar, 0–1. */
	at: number;
	color: string;
}

export function gradientStops(regime: TemperatureRegime): GradientStop[] {
	const stops = regime === 'stellar' ? STELLAR_STOPS : PLANETARY_STOPS;
	return stops.map(([kelvin, color]) => ({ at: scalePosition(kelvin, regime), color }));
}
