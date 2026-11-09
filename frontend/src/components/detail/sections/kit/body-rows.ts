/**
 * A body's mass and density as the export chose them, for the rows and the
 * stat cards that show them. A system mass, and the density over it, say they
 * are the system's: a reader would take them for the body's.
 */
import * as m from '$lib/paraglide/messages.js';
import type { GlobalObjectData, QuantityWithUnit } from '$lib/fetch/objects/object-data';
import { densityComparison } from '$lib/format/density';
import { formatMass, massComparison } from '$lib/format/mass';
import { formatDensity } from '$lib/format/quantities';

export interface BodyValueRow {
	label: string;
	/** What the label means, where the label alone does not say. */
	tooltip?: string;
	value: string;
	/** What the figure comes to against one a reader knows. */
	valueTooltip?: string;
	/** The word after a value that is not a measurement. */
	note?: string;
}

/** The word on a nominal value, as a planet's estimated values carry it. */
export function nominalNote(nominal: boolean | undefined): string | undefined {
	return nominal ? m.exoplanet_estimated() : undefined;
}

export function massRow(global: GlobalObjectData | null): BodyValueRow | null {
	const kg = global?.mass_kg;
	if (kg == null) return null;
	const system = global?.mass_system === true;
	return {
		label: system ? m.binary_system_mass() : m.property_name_mass(),
		tooltip: system ? m.tooltip_system_mass() : undefined,
		value: formatMass(kg),
		valueTooltip: massComparison(kg),
		note: nominalNote(global?.mass_nominal)
	};
}

/** The Binary system section's system mass, from AsterSat's orbit fit or
 *  Johnston's paper. None where the export's mass is the system's: that one
 *  shows once, as the body's mass. */
export function binarySystemMass(global: GlobalObjectData): QuantityWithUnit | undefined {
	if (global.mass_system) return undefined;
	return global.astersat?.system_mass ?? global.johnston?.mass;
}

/** The word on `binarySystemMass` where it is Johnston's assumed or
 *  estimated mass. */
export function binarySystemMassNote(global: GlobalObjectData): string | undefined {
	if (!binarySystemMass(global) || global.astersat?.system_mass) return undefined;
	return nominalNote(global.johnston?.mass_nominal);
}

export function densityRow(global: GlobalObjectData | null): BodyValueRow | null {
	const density = global?.mean_density_g_cm3;
	if (density == null) return null;
	const system = global?.mass_system === true;
	return {
		label: system ? m.system_density() : m.property_name_density(),
		tooltip: system ? m.tooltip_system_density() : undefined,
		value: formatDensity(density),
		valueTooltip: densityComparison(density),
		note: nominalNote(global?.mean_density_nominal)
	};
}
