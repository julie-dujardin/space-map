/**
 * Names for the atmosphere cross-section's layers, the notes that qualify a
 * single boundary, and the one that qualifies the whole envelope.
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

const TYPE_NAME: Record<string, () => string> = {
	exosphere: m.atmosphere_type_exosphere,
	tenuous_exosphere: m.atmosphere_type_tenuous_exosphere,
	transient_exosphere: m.atmosphere_type_transient_exosphere,
	tenuous_collisional: m.atmosphere_type_tenuous_collisional,
	thin_atmosphere: m.atmosphere_type_thin_atmosphere,
	thick_atmosphere: m.atmosphere_type_thick_atmosphere,
	gas_giant_envelope: m.atmosphere_type_gas_giant_envelope,
	stellar_atmosphere: m.atmosphere_type_stellar_atmosphere,
	localized_plume: m.atmosphere_type_localized_plume,
	frozen_collapsed: m.atmosphere_type_frozen_collapsed,
	none_detected: m.atmosphere_type_none_detected
};

/** What kind of atmosphere this is, said in one phrase. Falls back to the key,
 *  which is at least readable — the classification is the section's first row
 *  and an empty one reads as missing data. */
export function atmosphereTypeName(type: string): string {
	const fn = TYPE_NAME[type];
	if (!fn) {
		console.warn(`Missing atmosphere type: ${type}`);
		return type;
	}
	return fn();
}

// What keeps this atmosphere the way it is — the half the classification
// leaves unsaid, and the reason a pressure can be "variable".
const NOTE: Record<string, () => string> = {
	photosphere: m.atmosphere_note_photosphere,
	surface_bounded: m.atmosphere_note_surface_bounded,
	sputtered_ice: m.atmosphere_note_sputtered_ice,
	volcanic: m.atmosphere_note_volcanic,
	seasonal_cap: m.atmosphere_note_seasonal_cap,
	seasonal_orbit: m.atmosphere_note_seasonal_orbit,
	frozen_out: m.atmosphere_note_frozen_out,
	no_detection: m.atmosphere_note_no_detection,
	plume: m.atmosphere_note_plume,
	transient_vapour: m.atmosphere_note_transient_vapour
};

/** `no_surface` has no sentence anywhere: "Cloud-top pressure" already says
 *  where the figures are quoted, and the interior panel's Differentiation row
 *  already says the body has no solid surface. Saying it a third time in prose
 *  was three lines for one fact. */
const SILENT_NOTES = new Set(['no_surface']);

/** Beside the cross-section, `photosphere` goes too — the chart names its datum
 *  along the ground and again at the outer edge of the interior disc, so the
 *  sentence is a caption repeating the picture. It keeps its place next to the
 *  pressure row, where it defines what a photosphere is. */
const DATUM_NOTES = new Set(['photosphere']);

export function atmosphereNote(note: string | undefined): string | null {
	if (!note || SILENT_NOTES.has(note)) return null;
	const fn = NOTE[note];
	if (!fn) {
		console.warn(`Missing atmosphere note: ${note}`);
		return null;
	}
	return fn();
}

/** The same note, for the cross-section, which says the datum ones itself. */
export function atmosphereNoteBesideChart(note: string | undefined): string | null {
	if (!note || DATUM_NOTES.has(note)) return null;
	return atmosphereNote(note);
}

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
