/**
 * The Interior table of the extrasolar export (`docs/export-format/extrasolar.md`,
 * "Interior"): the interior of a star, from a paper (tier 0) or fitted to
 * stellar models (tiers 1 to 3).
 *
 * The table has no bit in the Metadata mask, so the lookup does not fetch it.
 * A star's panel asks for the row of its cell. The table is `site-only`, so an
 * embed never fetches it.
 */

import type { InteriorBlock } from '$lib/fetch/objects/object-data';
import { extrasolarLookup, type ExtrasolarLookup, type TableRow } from './lookup';

export const INTERIOR_SLUG = 'interior';

/** A tier-0 row is from a paper; tiers 1 to 3 are fits, best first. */
export const CURATED_TIER = 0;
/** The tier with no centre values. */
export const ROUGH_TIER = 3;

/** The [Fe/H] source of a fit with no metallicity of its own. */
export const ASSUMED_SOLAR = 'assumed-solar';

/** A fitted quantity: its value where the table gives one, and its range. */
export interface Fitted {
	value: number | null;
	range: [number, number] | null;
}

export interface StarInterior {
	id: number;
	tier: number;
	/** Tier 0 only: the paper's block, in the shape of a body's. */
	curated: InteriorBlock | null;
	/** `main_sequence`, `red_giant_branch`, `core_helium_burning`,
	 *  `asymptotic_giant_branch`. */
	stage: string | null;
	feh: number | null;
	fehSource: string | null;
	/** K: the Teff of the fit. A curated block has its paper's Teff on its
	 *  outermost layer. */
	teff: number | null;
	teffSource: string | null;
	luminositySource: string | null;
	/** M☉. */
	mass: Fitted;
	/** R☉, the radius of the fit. */
	radius: Fitted;
	/** r/R and m/M of the base of the outer convective zone. */
	envelopeBaseRadius: Fitted;
	envelopeBaseMass: Fitted;
	/** M☉, ranges only. */
	convectiveCoreMass: [number, number] | null;
	heliumCoreMass: [number, number] | null;
	/** K and g/cm³; none on tier 3. */
	centreTemperature: Fitted;
	centreDensity: Fitted;
	/** Mass fractions at the centre, ranges only; none on tier 3. */
	centreX: [number, number] | null;
	centreY: [number, number] | null;
}

function range(row: TableRow, name: string): [number, number] | null {
	const low = row.number(`${name}_lower`);
	const high = row.number(`${name}_upper`);
	return low === null || high === null ? null : [low, high];
}

function fitted(row: TableRow, name: string): Fitted {
	return { value: row.number(name), range: range(row, name) };
}

export function readStarInterior(row: TableRow): StarInterior {
	const curated = row.text('curated');
	return {
		id: row.number('id')!,
		tier: row.number('tier')!,
		curated: curated ? (JSON.parse(curated) as InteriorBlock) : null,
		stage: row.text('stage'),
		feh: row.number('feh'),
		fehSource: row.text('feh_source'),
		teff: row.number('teff'),
		teffSource: row.text('teff_source'),
		luminositySource: row.text('luminosity_source'),
		mass: fitted(row, 'mass'),
		radius: fitted(row, 'radius'),
		envelopeBaseRadius: fitted(row, 'envelope_base_radius'),
		envelopeBaseMass: fitted(row, 'envelope_base_mass'),
		convectiveCoreMass: range(row, 'convective_core_mass'),
		heliumCoreMass: range(row, 'helium_core_mass'),
		centreTemperature: fitted(row, 'centre_temperature'),
		centreDensity: fitted(row, 'centre_density'),
		centreX: range(row, 'centre_x'),
		centreY: range(row, 'centre_y')
	};
}

/** The interior of the star `id`, or null where it has none or the host may
 *  not show the table. */
export async function fetchStarInterior(
	id: number,
	lookup: ExtrasolarLookup = extrasolarLookup
): Promise<StarInterior | null> {
	const row = await lookup.row(INTERIOR_SLUG, id);
	return row && readStarInterior(row);
}
