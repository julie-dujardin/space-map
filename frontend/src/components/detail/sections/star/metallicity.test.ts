import { describe, expect, it } from 'vitest';
import type { TableRow } from '$lib/fetch/extrasolar/lookup';
import { pointSourceRecord } from '$lib/fetch/extrasolar/__fixtures__/record';
import type { ColumnSpec } from '$lib/fetch/extrasolar/__fixtures__/writer';
import { chooseMetallicity, starKind } from './metallicity';

/** The text without its bidi isolates and with plain spaces. */
const ISOLATES = new RegExp('[\\u2066-\\u2069]', 'g');
const NO_BREAK = new RegExp('\\u00a0', 'g');
const plain = (s: string) => s.replace(ISOLATES, '').replace(NO_BREAK, ' ');

type Value = number | string | boolean | null;
const STRINGS = new Set(['flags_gspspec', 'feh_xhip_quality']);
const BOOLS = new Set(['in_vetted_rgb_sample', 'in_oba_golden_sample', 'activity_lamost']);

/** A Point source row at 10 pc with these values. */
function row(values: Record<string, Value>): TableRow {
	const all: Record<string, Value> = { parallax: 100, parallax_error: 0.1, ...values };
	const columns = Object.entries(all).map(
		([name, value]): ColumnSpec => ({
			name,
			type: STRINGS.has(name) ? 'string' : BOOLS.has(name) ? 'bool' : 'float32',
			values: [value]
		})
	);
	return pointSourceRecord(columns).rows.get('point-source')!;
}

/** G and a BP − RP colour, as Gaia gives them. */
const colour = (g: number, bpRp: number) => ({
	phot_g_mean_mag: g,
	phot_bp_mean_mag: g + bpRp / 2,
	phot_rp_mean_mag: g - bpRp / 2
});
// At 10 pc the absolute G is the apparent G.
const DWARF = colour(5, 0.8);
const GIANT = colour(0.5, 1.2);
const M_DWARF = colour(9, 2.2);
const OBA = colour(1, 0.1);
const GOOD_FLAGS = '0'.repeat(41);

const chosen = (values: Record<string, Value>) => {
	const result = chooseMetallicity(row(values), 'dex');
	return result && { value: plain(result.value), source: result.source };
};

describe('the kind of a star', () => {
	it('splits by colour and absolute magnitude', () => {
		expect(starKind(row(OBA))).toBe('oba');
		expect(starKind(row(DWARF))).toBe('fgkDwarf');
		expect(starKind(row(GIANT))).toBe('giant');
		expect(starKind(row(M_DWARF))).toBe('mDwarf');
		expect(starKind(row({ parallax: null, ...DWARF }))).toBe(null);
	});
});

describe('the metallicity of each kind', () => {
	const pastel = { feh_pastel: -0.1, feh_pastel_min: -0.2, feh_pastel_max: 0.05 };
	const apogee = { feh_apogee: -0.12, feh_apogee_error: 0.01, mh_apogee: -0.1 };
	const xhip = { feh_xhip: -0.3, feh_xhip_error: 0.05, feh_xhip_quality: 'A' };
	const gspspec = {
		mh_gspspec: -0.2,
		mh_gspspec_lower: -0.3,
		mh_gspspec_upper: -0.1,
		mh_gspspec_calibrated: -0.25,
		fem_gspspec: 0.0,
		fem_gspspec_lower: -0.05,
		fem_gspspec_upper: 0.05,
		feh_gspspec_calibrated: -0.15,
		flags_gspspec: GOOD_FLAGS
	};
	const xp = { mh_xgboost: -0.4, in_vetted_rgb_sample: false, in_oba_golden_sample: false };
	const gspphot = { mh_gspphot: -0.8, mh_gspphot_lower: -0.9, mh_gspphot_upper: -0.7 };
	const lamost = { mh_lamost: 0.1, mh_lamost_error: 0.12, activity_lamost: false };

	it('takes PASTEL first for an FGK dwarf, with its range', () => {
		const all = { ...DWARF, ...pastel, ...apogee, ...xhip, ...gspspec, ...xp, ...gspphot };
		expect(chosen(all)).toEqual({ value: '-0.10 dex (-0.20 – 0.05 dex)', source: 'pastel-2020' });
		expect(chosen({ ...DWARF, ...apogee, ...xhip })).toEqual({
			value: '-0.120 ± 0.010 dex',
			source: 'apogee-dr17'
		});
		expect(chosen({ ...DWARF, ...xhip, ...gspspec })?.source).toBe('xhip');
		// Symmetric bounds read as one ±.
		expect(chosen({ ...DWARF, ...gspspec, ...xp })).toEqual({
			value: '-0.150 ± 0.050 dex',
			source: 'gaia-dr3-gspspec'
		});
		expect(chosen({ ...DWARF, ...xp, ...gspphot })?.source).toBe('andrae-2023');
	});

	it('puts GSP-Spec before XHIP for a giant', () => {
		expect(chosen({ ...GIANT, ...xhip, ...gspspec })?.source).toBe('gaia-dr3-gspspec');
		expect(chosen({ ...GIANT, ...apogee, ...gspspec })?.source).toBe('apogee-dr17');
	});

	it('takes APOGEE, then LAMOST, then GSP-Spec [M/H] for an M dwarf', () => {
		expect(chosen({ ...M_DWARF, ...apogee, ...lamost })).toEqual({
			value: '-0.10 dex',
			source: 'apogee-dr17'
		});
		expect(chosen({ ...M_DWARF, ...lamost, ...gspspec })).toEqual({
			value: '0.10 ± 0.12 dex',
			source: 'lamost-dr10'
		});
		const active = { ...lamost, activity_lamost: true };
		expect(chosen({ ...M_DWARF, ...active, ...gspspec })).toEqual({
			value: '-0.25 ± 0.10 dex',
			source: 'gaia-dr3-gspspec'
		});
		// XP holds up to BP − RP 2.5, before GSP-Phot.
		expect(chosen({ ...M_DWARF, ...xp, ...gspphot })?.source).toBe('andrae-2023');
		expect(chosen({ ...colour(10, 2.6), ...xp, ...gspphot })?.source).toBe('gaia-dr3-gspphot');
	});

	it('shows only spectra of hot stars for an O, B or A star, never GSP-Phot', () => {
		expect(chosen({ ...OBA, ...xhip, ...gspspec, ...gspphot })?.source).toBe('xhip');
		expect(chosen({ ...OBA, ...pastel, ...xhip })?.source).toBe('pastel-2020');
		expect(chosen({ ...OBA, ...gspspec, ...xp, ...gspphot })).toBe(null);
	});

	it('applies the cut of each source', () => {
		// KMgiantPar (13th flag) set: GSP-Spec is out.
		const flagged = { ...gspspec, flags_gspspec: '0'.repeat(12) + '1' + '0'.repeat(28) };
		expect(chosen({ ...DWARF, ...flagged, ...gspphot })?.source).toBe('gaia-dr3-gspphot');
		// fluxNoise (7th flag) up to 3 holds.
		const noisy = { ...gspspec, flags_gspspec: '0'.repeat(6) + '3' + '0'.repeat(34) };
		expect(chosen({ ...DWARF, ...noisy })?.source).toBe('gaia-dr3-gspspec');
		expect(chosen({ ...DWARF, ...xhip, feh_xhip_quality: 'C', ...gspphot })?.source).toBe(
			'gaia-dr3-gspphot'
		);
		// XP holds from BP − RP 0.5, so a bluer FGK dwarf falls to GSP-Phot.
		expect(chosen({ ...colour(3, 0.45), ...xp, ...gspphot })?.source).toBe('gaia-dr3-gspphot');
		expect(chosen({ ...colour(5, 1.6), ...xp, ...gspphot })?.source).toBe('andrae-2023');
	});

	it('gives the quantity of the column it takes', () => {
		const quantity = (values: Record<string, Value>) =>
			chooseMetallicity(row(values), 'dex')?.quantity;
		expect(quantity({ ...DWARF, ...pastel })).toBe('feh');
		expect(quantity({ ...DWARF, ...apogee })).toBe('feh');
		expect(quantity({ ...M_DWARF, ...apogee })).toBe('mh');
		expect(quantity({ ...M_DWARF, feh_apogee: -0.12 })).toBe('feh');
		expect(quantity({ ...DWARF, ...xhip })).toBe('feh');
		expect(quantity({ ...DWARF, ...gspspec })).toBe('feh');
		// GSP-Spec falls back to [M/H] where [Fe/H] does not hold.
		expect(quantity({ ...DWARF, ...gspspec, fem_gspspec: null })).toBe('mh');
		expect(quantity({ ...M_DWARF, ...gspspec })).toBe('mh');
		expect(quantity({ ...M_DWARF, ...lamost })).toBe('mh');
		expect(quantity({ ...DWARF, ...xp })).toBe('mh');
		expect(quantity({ ...DWARF, ...gspphot })).toBe('mh');
	});

	it('uses the FGK dwarf order without a kind, and nothing without a value', () => {
		expect(chosen({ parallax: null, ...DWARF, ...pastel, ...xp })?.source).toBe('pastel-2020');
		expect(chosen({ ...DWARF })).toBe(null);
	});
});
