/**
 * The credited imagery layers, declared once. The scene store, the attribution
 * popover and /credits all key off this table, so a new layer needs an entry
 * here and a register call — not a field in six unrelated files.
 *
 * Mirrors the sibling-bundle shape in `data/src/space_map_data/export/credits.py`.
 */
import * as m from '$lib/paraglide/messages.js';
import type { TextureDistribution } from '$lib/host';

export type ImageryLayer =
	| 'surface'
	| 'clouds'
	| 'night'
	| 'glow'
	| 'specular'
	| 'topography'
	| 'rings';

/** Row order wherever layers of one body are listed together. */
export const IMAGERY_LAYERS: readonly ImageryLayer[] = [
	'surface',
	'clouds',
	'night',
	'glow',
	'specular',
	'topography',
	'rings'
];

/** `Record` rather than a lookup: a new layer fails to compile without a label. */
const LAYER_LABELS: Record<ImageryLayer, () => string> = {
	surface: m.attribution_type_surface,
	clouds: m.attribution_type_clouds,
	night: m.attribution_type_night,
	glow: m.attribution_type_glow,
	specular: m.attribution_type_specular,
	topography: m.attribution_type_topography,
	rings: m.attribution_type_rings
};

export function layerLabel(layer: ImageryLayer): string {
	return LAYER_LABELS[layer]();
}

/** The note on a credit row: the layer, where the body has several, and the
 *  mark of an artist's impression. Undefined for neither. */
export function rowQualifier(
	layer: ImageryLayer | undefined,
	artistImpression: boolean | undefined
): string | undefined {
	const parts = [layer && layerLabel(layer), artistImpression && m.artist_impression_qualifier()];
	return parts.filter(Boolean).join(', ') || undefined;
}

/** The credit fields every layer's metadata block carries. */
export interface CreditFields {
	source: string;
	organisation: string;
	license?: string;
	/** Who may serve this layer, absent where anyone may — see
	 *  `textureAllowed` in `$lib/host`. Only surface maps carry one today. */
	distribution?: TextureDistribution;
	attribution?: string;
	description?: string;
	/** An artist's picture of a body no camera has resolved. */
	artist_impression?: boolean;
}
