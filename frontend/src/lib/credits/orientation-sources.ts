/**
 * Who published a body's rotational elements, and who measured its shape.
 *
 * The export merges four disjoint sets into one orientation table — the
 * IAU/NAIF PCK constants, poles converted from DAMIT's lightcurve inversions,
 * and the occultation and photometric fits of the small bodies no kernel
 * covers — and tags each record with its `source` (see `load_orientation` in
 * export/systems.py). The last two name their own paper on the record.
 *
 * Single source of truth for both surfaces that credit a pole: the detail
 * sidebar, which quotes the rotation period as a value, and the scene's
 * attribution popover, which credits the elements the renderer spins bodies by.
 */
import * as m from '$lib/paraglide/messages.js';

/** A fit published as a named work, so the record carries its own citation.
 *  Tags a pole and, separately, an ellipsoid — often from different papers. */
export type MeasuredShapeSource = 'occultation' | 'photometry';

export type OrientationSource = 'pck' | 'lightcurve' | MeasuredShapeSource;

export interface OrientationReference {
	title: string;
	url: string;
}

export interface OrientationCreditEntry {
	/** Dedup key across both surfaces. */
	key: string;
	/** Compact form for the sidebar's inline source list. */
	short: string;
	/** Full name for the popover, which has the width for it. */
	long: string;
	url: string;
	/** What this source contributed, shown as the sidebar's parenthetical. */
	role: string;
}

const IAU_WGCCRE_URL = 'https://www.iau.org/WG100/WG100/Home.aspx';
const NAIF_URL = 'https://naif.jpl.nasa.gov/naif/';
const DAMIT_URL = 'https://damit.cuni.cz/';

/**
 * Credits for one body's rotational elements. `undefined` source means a
 * pre-`source` bundle, which is always PCK — that's all the table held before
 * the other two sets were merged in.
 */
export function orientationCredits(
	source: OrientationSource | undefined,
	reference?: OrientationReference
): OrientationCreditEntry[] {
	if (source === 'lightcurve')
		return [
			{
				key: 'damit',
				short: m.source_damit_name(),
				long: m.source_damit_name(),
				url: DAMIT_URL,
				role: m.source_spin_pole_role()
			}
		];
	// These bodies appear in no kernel; their pole comes from the paper the
	// record names, so there is nothing generic to credit.
	if (source === 'occultation' || source === 'photometry')
		return reference ? [namedWorkCredit(reference, m.source_spin_pole_role())] : [];
	// The IAU working group sets the elements, NAIF is where we read them.
	return [
		{
			key: 'iau-wgccre',
			short: m.source_iau_wgccre_short(),
			long: m.source_iau_wgccre_name(),
			url: IAU_WGCCRE_URL,
			role: m.source_iau_wgccre_role()
		},
		{
			key: 'naif',
			short: m.source_spice_pck_name(),
			long: m.source_spice_pck_name(),
			url: NAIF_URL,
			role: m.source_spice_pck_role()
		}
	];
}

/** Credit for the work that fitted a body's ellipsoid. Separate from the pole:
 *  a shape measured off occultation chords and a pole from years of photometry
 *  are routinely two different papers. */
export function measuredShapeCredit(reference: OrientationReference): OrientationCreditEntry {
	return namedWorkCredit(reference, m.source_shape_role());
}

function namedWorkCredit(reference: OrientationReference, role: string): OrientationCreditEntry {
	return {
		key: reference.url,
		short: reference.title,
		long: reference.title,
		url: reference.url,
		role
	};
}
