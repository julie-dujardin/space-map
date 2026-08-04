/**
 * Names for the interior cross-section's layers: what a shell is called and
 * what phase it is in.
 *
 * The pipeline ships keys and the names live here, the same contract the
 * composition bar's materials use, so the prose stays translatable.
 */

import * as m from '$lib/paraglide/messages.js';

const LAYER_NAME: Record<string, () => string> = {
	crust: m.interior_layer_crust,
	ice_shell: m.interior_layer_ice_shell,
	ocean: m.interior_layer_ocean,
	mantle: m.interior_layer_mantle,
	ice_mantle: m.interior_layer_ice_mantle,
	magma: m.interior_layer_magma,
	envelope: m.interior_layer_envelope,
	metallic_hydrogen: m.interior_layer_metallic_hydrogen,
	radiative_zone: m.interior_layer_radiative_zone,
	convective_zone: m.interior_layer_convective_zone,
	core: m.interior_layer_core,
	outer_core: m.interior_layer_outer_core,
	inner_core: m.interior_layer_inner_core,
	bulk: m.interior_layer_bulk
};

const STATE_NAME: Record<string, () => string> = {
	solid: m.interior_state_solid,
	liquid: m.interior_state_liquid,
	partial_melt: m.interior_state_partial_melt,
	fluid: m.interior_state_fluid,
	plasma: m.interior_state_plasma
};

/** Notes that name the shell instead of footnoting it: what the numbers are of
 *  is the shell's identity, and Earth's crust card is entirely continental.
 *  Every other layer note is provenance metadata a card already conveys — the
 *  published range around a modelled value — so none of them earn a sentence. */
const NAME_BY_NOTE: Record<string, () => string> = {
	continental_crust_only: m.interior_layer_continental_crust
};

export function layerName(role: string, note?: string): string {
	const named = note ? NAME_BY_NOTE[note] : undefined;
	if (named) return named();
	const fn = LAYER_NAME[role];
	if (!fn) {
		console.warn(`Missing interior layer name: ${role}`);
		return role;
	}
	return fn();
}

export function stateName(state: string): string {
	const fn = STATE_NAME[state];
	if (!fn) {
		console.warn(`Missing interior state name: ${state}`);
		return state;
	}
	return fn();
}
