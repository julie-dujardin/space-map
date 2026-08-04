/**
 * Who published a body's rotational elements.
 *
 * The export merges three disjoint sets into one orientation table — the
 * IAU/NAIF PCK constants, poles converted from DAMIT's lightcurve inversions,
 * and the occultation fits of the four ringed small bodies — and tags each
 * record with its `source` (see `load_orientation` in export/systems.py).
 *
 * Single source of truth for both surfaces that credit a pole: the detail
 * sidebar, which quotes the rotation period as a value, and the scene's
 * attribution popover, which credits the elements the renderer spins bodies by.
 */
import * as m from '$lib/paraglide/messages.js';

export type OrientationSource = 'pck' | 'lightcurve' | 'occultation';

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
	// The ringed small bodies appear in no kernel; their pole comes from the
	// occultation paper the record names, so there is nothing generic to credit.
	if (source === 'occultation')
		return reference
			? [
					{
						key: reference.url,
						short: reference.title,
						long: reference.title,
						url: reference.url,
						role: m.source_spin_pole_role()
					}
				]
			: [];
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
