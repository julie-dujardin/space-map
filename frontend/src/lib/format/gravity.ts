import * as m from '$lib/paraglide/messages.js';
import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
import { G0_M_S2 } from '$lib/math/travel/constants';
import { formatUnit, joinParts, scientificNotation, sigFigures } from './quantities';

// The two rungs the export's Wikidata acceleration ladder actually emits.
const MS2_PER_UNIT: Record<string, number> = {
	metres_per_second_squared: 1,
	centimetre_per_square_second: 0.01
};

// Keyed by the same reference level the headline pressure is quoted at:
// "surface" on a giant or the Sun would claim a floor that isn't there. The
// label off the surface is just "Gravity" (a stat card is 92px wide), so the
// tooltip spells the level out.
const GRAVITY_LABEL: Record<string, () => string> = {
	cloud_top: m.gravity_cloud_top,
	photosphere: m.gravity_photosphere
};
const GRAVITY_TOOLTIP: Record<string, () => string> = {
	cloud_top: m.tooltip_gravity_cloud_top,
	photosphere: m.tooltip_gravity_photosphere
};

function pressureLevel(global: GlobalObjectData | null): string | undefined {
	return global?.atmosphere?.pressure?.level;
}

export function gravityLabel(global: GlobalObjectData | null): string {
	const level = pressureLevel(global);
	return ((level && GRAVITY_LABEL[level]) || m.gravity_surface)();
}

export function gravityTooltip(global: GlobalObjectData | null): string {
	const level = pressureLevel(global);
	return ((level && GRAVITY_TOOLTIP[level]) || m.tooltip_gravity_surface)();
}

/** Back to m/s² from whatever unit the source published, null if unknown. */
export function accelMs2(q: { value: number; unit: string }): number | null {
	const factor = MS2_PER_UNIT[q.unit];
	return factor === undefined ? null : q.value * factor;
}

// Below this Intl spells a row of leading zeros; a comet's gravity is a
// real number, not 0.00 — see the never-cap rule.
const SCIENTIFIC_FLOOR = 0.001;

function figure(value: number): string {
	return value >= SCIENTIFIC_FLOOR ? sigFigures(value, 2) : scientificNotation(value);
}

/** "0.38 g" — gravity against the one field anyone has a feel for. */
export function formatGees(ms2: number): string {
	return joinParts({
		value: figure(ms2 / G0_M_S2),
		unit: m.symbol_standard_gravity()
	});
}

/** The same reading in SI, for the tooltip under the gees. */
export function formatMs2(ms2: number): string {
	return joinParts({ value: figure(ms2), unit: formatUnit('metres_per_second_squared', true) });
}
