/**
 * The metallicity a star's panel shows, and its source. Each catalogue is
 * best for some kinds of star, so the panel sorts the star into a kind by its
 * colour and absolute magnitude, then takes the first source in that kind's
 * order that has a value that holds. The kinds and the orders are choices of
 * display, so they live here and not in the export.
 */

import type { TableRow } from '$lib/fetch/extrasolar/lookup';
import { plusMinus, withBounds } from '$lib/format/star';
import { absoluteG, colourBpRp } from '$lib/scene/starfield/record';

/** The XP [M/H] holds below this observed BP − RP, the outer limit of Andrae,
 *  Rix & Chandra 2023 (Sect. 3.5). Above 1.5 it runs about 0.15 dex low, but
 *  it still beats GSP-Phot there. */
export const XP_MAX_COLOUR = 2.5;
/** GSP-Phot [M/H] for an O, B or A star: it is off by +0.5 dex against
 *  PASTEL, with a scatter of 0.6 dex, so it stays hidden. */
export const SHOW_GSPPHOT_FOR_OBA = false;

/** Observed BP − RP above which Andrae et al. find the XP [M/H] unbiased, and
 *  the G past which they advise removal (Sect. 3.5 and 4.3). */
const XP_MIN_COLOUR = 0.5;
const XP_MAX_G = 17.65;

/** BP − RP of an F0 and an M0 dwarf. */
const OBA_MAX_COLOUR = 0.4;
const M_DWARF_MIN_COLOUR = 1.84;
/** A giant is brighter than this absolute G: 2 mag over a straight main
 *  sequence, with no extinction. */
const GIANT_SLOPE = 2.8;
const GIANT_INTERCEPT = 0.3;

export type StarKind = 'oba' | 'fgkDwarf' | 'giant' | 'mDwarf';

/** The kind of a star; null without a colour or a distance. `orbit` is the
 *  record's `astrometricOrbit`, which can give the distance. */
export function starKind(ps: TableRow, orbit: TableRow | null): StarKind | null {
	const colour = colourBpRp(ps);
	const mag = absoluteG(ps, orbit);
	if (colour === null || mag === null) return null;
	if (colour < OBA_MAX_COLOUR) return 'oba';
	if (mag < GIANT_SLOPE * colour + GIANT_INTERCEPT) return 'giant';
	return colour < M_DWARF_MIN_COLOUR ? 'fgkDwarf' : 'mDwarf';
}

/** Where the XP [M/H] holds: their vetted red giants always (Sect. 4.2);
 *  otherwise inside the colour range and G limit, and not an OBA star of the
 *  Gaia golden sample, the list they name for that cut (Sect. 3.7 and 4.3). */
function xpHolds(ps: TableRow): boolean {
	if (ps.flag('in_vetted_rgb_sample')) return true;
	if (ps.flag('in_oba_golden_sample') !== false) return false;
	const g = ps.number('phot_g_mean_mag');
	const bp = ps.number('phot_bp_mean_mag');
	const rp = ps.number('phot_rp_mean_mag');
	if (g === null || bp === null || rp === null || g > XP_MAX_G) return false;
	return bp - rp > XP_MIN_COLOUR && bp - rp < XP_MAX_COLOUR;
}

/** The medium-quality cut of Recio-Blanco et al. 2023 (Sect. 9.1.1) on the
 *  first 13 GSP-Spec flags: each at most 1, but fluxNoise (7th) at most 3 and
 *  KMgiantPar (13th) 0. */
function gspspecHolds(ps: TableRow): boolean {
	const flags = ps.text('flags_gspspec');
	if (flags === null || flags.length < 13) return false;
	for (let i = 0; i < 13; i++) {
		const limit = i === 6 ? 3 : i === 12 ? 0 : 1;
		if (!(Number(flags[i]) <= limit)) return false;
	}
	return true;
}

/** `value` with its bounds moved by `shift`, as a calibration moves them. */
function shifted(ps: TableRow, value: number, raw: number, name: string, dex: string): string {
	const low = ps.number(`${name}_lower`);
	const high = ps.number(`${name}_upper`);
	const shift = value - raw;
	return withBounds(
		value,
		low === null ? null : low + shift,
		high === null ? null : high + shift,
		dex
	);
}

/** The quantity of a metallicity column. */
export type MetallicityQuantity = 'mh' | 'feh';

/** A metallicity as the panel shows it, with the quantity of its column. */
export interface Metallicity {
	value: string;
	quantity: MetallicityQuantity;
}

/** A metallicity that a record can give, named for `starSourceName`. `value`
 *  is null where the star has none, or where it does not hold. */
interface MetallicitySource {
	source: string;
	value: (ps: TableRow, dex: string) => Metallicity | null;
}

function metallicity(quantity: MetallicityQuantity, value: string | null): Metallicity | null {
	return value === null ? null : { value, quantity };
}

function valueWithError(ps: TableRow, name: string, dex: string): string | null {
	const value = ps.number(name);
	return value === null ? null : plusMinus(value, ps.number(`${name}_error`), dex);
}

const PASTEL: MetallicitySource = {
	// The median of the determinations, with their range.
	source: 'pastel-2020',
	value: (ps, dex) => {
		const feh = ps.number('feh_pastel');
		if (feh === null) return null;
		return metallicity(
			'feh',
			withBounds(feh, ps.number('feh_pastel_min'), ps.number('feh_pastel_max'), dex)
		);
	}
};
const APOGEE_FEH: MetallicitySource = {
	source: 'apogee-dr17',
	value: (ps, dex) =>
		metallicity('feh', valueWithError(ps, 'feh_apogee', dex)) ??
		metallicity('mh', valueWithError(ps, 'mh_apogee', dex))
};
const APOGEE_MH: MetallicitySource = {
	source: 'apogee-dr17',
	value: (ps, dex) =>
		metallicity('mh', valueWithError(ps, 'mh_apogee', dex)) ??
		metallicity('feh', valueWithError(ps, 'feh_apogee', dex))
};
const XHIP: MetallicitySource = {
	// Quality C is uncalibrated.
	source: 'xhip',
	value: (ps, dex) => {
		const quality = ps.text('feh_xhip_quality');
		return quality === 'A' || quality === 'B'
			? metallicity('feh', valueWithError(ps, 'feh_xhip', dex))
			: null;
	}
};
const GSPSPEC_MH: MetallicitySource = {
	source: 'gaia-dr3-gspspec',
	value: (ps, dex) => {
		const mh = ps.number('mh_gspspec_calibrated');
		const raw = ps.number('mh_gspspec');
		if (mh === null || raw === null || !gspspecHolds(ps)) return null;
		return metallicity('mh', shifted(ps, mh, raw, 'mh_gspspec', dex));
	}
};
const GSPSPEC: MetallicitySource = {
	// [Fe/H] where its calibration holds, with the range of [Fe/M]; else [M/H].
	source: 'gaia-dr3-gspspec',
	value: (ps, dex) => {
		const feh = ps.number('feh_gspspec_calibrated');
		const fem = ps.number('fem_gspspec');
		if (feh === null || fem === null || !gspspecHolds(ps)) return GSPSPEC_MH.value(ps, dex);
		return metallicity('feh', shifted(ps, feh, fem, 'fem_gspspec', dex));
	}
};
const LAMOST: MetallicitySource = {
	// Zhang et al. 2025 advise caution for stars with Hα emission.
	source: 'lamost-dr10',
	value: (ps, dex) =>
		ps.flag('activity_lamost') === false
			? metallicity('mh', valueWithError(ps, 'mh_lamost', dex))
			: null
};
const XP: MetallicitySource = {
	// No uncertainty for each star.
	source: 'andrae-2023',
	value: (ps, dex) => {
		const mh = ps.number('mh_xgboost');
		return mh !== null && xpHolds(ps) ? metallicity('mh', plusMinus(mh, null, dex, 2)) : null;
	}
};
const GSPPHOT: MetallicitySource = {
	// Last everywhere: its own paper calls its [M/H] biased.
	source: 'gaia-dr3-gspphot',
	value: (ps, dex) => {
		const mh = ps.number('mh_gspphot');
		if (mh === null) return null;
		return metallicity(
			'mh',
			withBounds(mh, ps.number('mh_gspphot_lower'), ps.number('mh_gspphot_upper'), dex)
		);
	}
};

const FGK_DWARF_ORDER = [PASTEL, APOGEE_FEH, XHIP, GSPSPEC, XP, GSPPHOT];

/** The sources of each kind, best first. Only spectra of hot stars hold for
 *  O, B and A stars; GSP-Spec and XP are off there by about 0.5 dex. An O, B
 *  or A star without one has no metallicity row. */
export const METALLICITY_ORDER: Record<StarKind, readonly MetallicitySource[]> = {
	oba: [PASTEL, XHIP, ...(SHOW_GSPPHOT_FOR_OBA ? [GSPPHOT] : [])],
	fgkDwarf: FGK_DWARF_ORDER,
	giant: [PASTEL, APOGEE_FEH, GSPSPEC, XHIP, XP, GSPPHOT],
	mDwarf: [APOGEE_MH, LAMOST, GSPSPEC_MH, XP, GSPPHOT]
};

/** The metallicity to show and its source; null where no source has one. */
export function chooseMetallicity(
	ps: TableRow,
	orbit: TableRow | null,
	dex: string
): (Metallicity & { source: string }) | null {
	const kind = starKind(ps, orbit);
	for (const { source, value } of kind ? METALLICITY_ORDER[kind] : FGK_DWARF_ORDER) {
		const found = value(ps, dex);
		if (found !== null) return { ...found, source };
	}
	return null;
}
