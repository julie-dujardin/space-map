/** The mode names. The picker and the trajectory use this file. */

import * as m from '$lib/paraglide/messages.js';
import { getLocale } from '$lib/paraglide/runtime.js';
import { formatKm } from '$lib/format/distance';
import { formatDegrees } from '$lib/format/quantities';
import type { LaunchPad } from '$lib/travel/launch-pad';
import type { EndpointMode } from '$lib/travel/trip';

const LABELS: Record<EndpointMode, () => string> = {
	surface: () => m.travel_mode_surface(),
	'low-orbit': () => m.travel_mode_low_orbit(),
	elliptical: () => m.travel_mode_elliptical(),
	'semi-sync': () => m.travel_mode_semi_sync(),
	stationary: () => m.travel_mode_stationary(),
	transfer: () => m.travel_mode_transfer(),
	heo: () => m.travel_mode_heo(),
	custom: () => m.travel_mode_custom(),
	rendezvous: () => m.travel_mode_rendezvous(),
	flyby: () => m.travel_mode_flyby()
};

/** Give the altitudes if you know them. A custom orbit shows its shape: one
 *  height where it is circular, both ends where it is not. */
export function endpointModeLabel(
	mode: EndpointMode,
	role: 'origin' | 'target',
	altKm: number | null = null,
	apoAltKm: number | null = null
): string {
	if (mode === 'surface')
		return role === 'origin' ? m.travel_mode_surface() : m.travel_mode_landing();
	if (mode !== 'custom' || altKm === null) return LABELS[mode]();
	if (apoAltKm === null || apoAltKm === altKm)
		return m.travel_orbit_at({ altitude: formatKm(altKm) });
	return m.travel_orbit_ellipse({ periapsis: formatKm(altKm), apoapsis: formatKm(apoAltKm) });
}

/** The plane beside its slider: the angle alone, since the words next to it
 *  would be the same on every reading and there is no room for them. */
export function planeReadout(incDeg: number | null): string {
	return incDeg === null ? m.travel_orbit_plane_free() : formatDegrees(incDeg);
}

/** Where periapsis sits, beside its slider. The quarter turns are the ones that
 *  mean something to a reader — the high point over a pole or over the equator —
 *  so they are named rather than left as an angle. */
export function argPeriReadout(argPeriDeg: number | null): string {
	if (argPeriDeg === null) return m.travel_orbit_arg_peri_free();
	if (argPeriDeg === 90) return m.travel_orbit_arg_peri_south();
	if (argPeriDeg === 270) return m.travel_orbit_arg_peri_north();
	return formatDegrees(argPeriDeg);
}

/**
 * The plane an end is met in, said in full. Above a quarter turn the orbit runs
 * against the body's own spin, which is the fact worth saying rather than the
 * angle it is stated as.
 */
export function planeLabel(incDeg: number | null): string {
	if (incDeg === null) return m.travel_orbit_plane_free();
	return incDeg > 90
		? m.travel_orbit_plane_retrograde({ degrees: formatDegrees(180 - incDeg) })
		: m.travel_orbit_plane_at({ degrees: formatDegrees(incDeg) });
}

/**
 * The ground line under an end's name: a pad name, or bare coordinates.
 * Fixed decimal rather than `formatNumber`'s significant digits, which would
 * drop a longitude's decimal past 100 while keeping its latitude's.
 */
export function groundLabel(
	role: 'origin' | 'target',
	pad: LaunchPad | null,
	place: { lat: number; lon: number } | null
): string | null {
	if (pad) return pad.name;
	if (!place) return null;
	const deg = (v: number) =>
		`${v.toLocaleString(getLocale(), { minimumFractionDigits: 1, maximumFractionDigits: 1 })}°`;
	return `${endpointModeLabel('surface', role)} · ${deg(place.lat)}, ${deg(place.lon)}`;
}
