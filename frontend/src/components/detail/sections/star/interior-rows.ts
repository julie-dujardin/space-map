/**
 * The rows above a star's cross-section: where its interior comes from, the
 * stage of the fit, and the centre of the star. A fit gives the centre as
 * ranges, so the rows show ranges. Tier 3 has no centre values.
 */

import * as m from '$lib/paraglide/messages.js';
import {
	ASSUMED_SOLAR,
	CURATED_TIER,
	ROUGH_TIER,
	type StarInterior
} from '$lib/fetch/extrasolar/interior';
import type { InteriorBlock } from '$lib/fetch/objects/object-data';
import { starSourceName } from '$lib/credits/star-sources';
import { ltrIsolate } from '$lib/format/bidi';
import { formatKelvin, formatKelvinRange } from '$lib/format/temperature';
import { formatSpan, joinParts, percentParts, quantityParts } from '$lib/format/quantities';
import { row, rows, type StarRowEntry } from './star-rows';

const STAGE_NAME: Record<string, () => string> = {
	main_sequence: m.star_stage_main_sequence,
	red_giant_branch: m.star_stage_red_giant_branch,
	core_helium_burning: m.star_stage_core_helium_burning,
	asymptotic_giant_branch: m.star_stage_asymptotic_giant_branch
};

const DENSITY_UNIT = 'gram_per_cubic_centimetre';

/** Where the interior comes from: the paper, or a fit and what it was fitted to. */
export function modelRow(interior: StarInterior, block: InteriorBlock): StarRowEntry | null {
	if (interior.tier === CURATED_TIER) {
		const paper = block.sources?.[0];
		return paper ? { label: m.star_interior_model(), value: paper.title, href: paper.url } : null;
	}
	return {
		label: m.star_interior_model(),
		value: m.star_interior_model_fit(),
		note: fitNote(interior),
		tooltip: fitInputs(interior)
	};
}

/** What a fit rests on, by its tier. A tier-3 star with a metallicity of its
 *  own is there for its distance or its multiplicity. */
function fitNote(interior: StarInterior): string {
	if (interior.fehSource === ASSUMED_SOLAR) return m.star_interior_inputs_solar();
	if (interior.tier === 1) return m.star_interior_inputs_measured();
	if (interior.tier === 2) return m.star_interior_inputs_photometric();
	return m.star_interior_inputs_uncertain();
}

function fitInputs(interior: StarInterior): string | undefined {
	const { teffSource, luminositySource, fehSource } = interior;
	if (!teffSource || !luminositySource) return undefined;
	const teff = starSourceName(teffSource);
	const luminosity = starSourceName(luminositySource);
	if (fehSource === ASSUMED_SOLAR || !fehSource) {
		return m.star_interior_inputs_solar_from({ teff, luminosity });
	}
	return m.star_interior_inputs_from({ teff, luminosity, feh: starSourceName(fehSource) });
}

/** Ends that round alike read as one figure. */
function percentSpan([low, high]: [number, number]): string {
	const [a, b] = [percentParts(low, 3), percentParts(high, 3)];
	return ltrIsolate(a.value === b.value ? joinParts(a) : formatSpan(a, b));
}

function densityText(value: number | undefined, range: [number, number] | undefined) {
	const parts = (v: number) => quantityParts({ value: v, unit: DENSITY_UNIT }, true);
	if (range) return ltrIsolate(formatSpan(parts(range[0]), parts(range[1])));
	return value === undefined ? null : ltrIsolate(joinParts(parts(value)));
}

function temperatureText(block: InteriorBlock): string | null {
	const range = block.centre_temperature_range_k;
	if (range) return formatKelvinRange(range[0], range[1]);
	const value = block.centre_temperature_k;
	return value === undefined ? null : formatKelvin(value);
}

export function starInteriorRows(interior: StarInterior, block: InteriorBlock): StarRowEntry[] {
	const stage = interior.stage ? STAGE_NAME[interior.stage]?.() : undefined;
	const centre = interior.tier !== ROUGH_TIER;
	return rows([
		modelRow(interior, block),
		row(m.star_row_evolutionary_stage(), stage),
		centre ? row(m.star_interior_centre_temperature(), temperatureText(block)) : null,
		centre
			? row(
					m.star_interior_centre_density(),
					densityText(block.centre_density_g_cm3, block.centre_density_range_g_cm3)
				)
			: null,
		row(
			m.star_interior_centre_hydrogen(),
			block.centre_hydrogen_range && percentSpan(block.centre_hydrogen_range)
		),
		row(
			m.star_interior_centre_helium(),
			block.centre_helium_range && percentSpan(block.centre_helium_range)
		)
	]);
}
