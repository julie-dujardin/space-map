/**
 * Names for the atmosphere cross-section's layers, and the notes that qualify
 * a single boundary rather than the whole envelope.
 */

import * as m from '$lib/paraglide/messages.js';

const LAYER_NAME: Record<string, () => string> = {
	boundary_layer: m.atmosphere_layer_boundary_layer,
	troposphere: m.atmosphere_layer_troposphere,
	stratosphere: m.atmosphere_layer_stratosphere,
	mesosphere: m.atmosphere_layer_mesosphere,
	thermosphere: m.atmosphere_layer_thermosphere,
	exosphere: m.atmosphere_layer_exosphere,
	photosphere: m.atmosphere_layer_photosphere,
	chromosphere: m.atmosphere_layer_chromosphere,
	transition_region: m.atmosphere_layer_transition_region,
	corona: m.atmosphere_layer_corona
};

const LAYER_NOTE: Record<string, () => string> = {
	well_mixed: m.atmosphere_structure_note_well_mixed,
	heterosphere: m.atmosphere_structure_note_heterosphere,
	no_inversion: m.atmosphere_structure_note_no_inversion,
	nightside_cryosphere: m.atmosphere_structure_note_nightside_cryosphere,
	seasonal_dust: m.atmosphere_structure_note_seasonal_dust,
	weakly_defined: m.atmosphere_structure_note_weakly_defined,
	diffuse_top: m.atmosphere_structure_note_diffuse_top,
	haze_layers: m.atmosphere_structure_note_haze_layers,
	cloud_deck: m.atmosphere_structure_note_cloud_deck,
	exobase: m.atmosphere_structure_note_exobase
};

export function atmosphereLayerName(role: string): string {
	const fn = LAYER_NAME[role];
	if (!fn) {
		console.warn(`Missing atmosphere layer name: ${role}`);
		return role;
	}
	return fn();
}

/** Falls back to nothing rather than to the key — a layer reads fine without
 *  its footnote, and a raw `diffuse_top` under one reads as a bug. */
export function atmosphereLayerNote(note: string): string {
	const fn = LAYER_NOTE[note];
	if (!fn) {
		console.warn(`Missing atmosphere layer note: ${note}`);
		return '';
	}
	return fn();
}
