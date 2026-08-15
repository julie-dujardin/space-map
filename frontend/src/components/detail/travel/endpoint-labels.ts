/** The mode names. The picker and the trajectory use this file. */

import * as m from '$lib/paraglide/messages.js';
import { formatKm } from '$lib/format/distance';
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
	flyby: () => m.travel_mode_flyby()
};

/** Give altKm if you know it. A custom orbit shows its height. */
export function endpointModeLabel(
	mode: EndpointMode,
	role: 'origin' | 'target',
	altKm: number | null = null
): string {
	if (mode === 'surface')
		return role === 'origin' ? m.travel_mode_surface() : m.travel_mode_landing();
	if (mode === 'custom' && altKm !== null) return m.travel_orbit_at({ altitude: formatKm(altKm) });
	return LABELS[mode]();
}
