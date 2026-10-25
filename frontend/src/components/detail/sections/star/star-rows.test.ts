import { describe, expect, it } from 'vitest';
import { ExtrasolarLookup, type ExtrasolarRecord } from '$lib/fetch/extrasolar/lookup';
import { HAS_EXPORT, diskSource } from '$lib/fetch/extrasolar/__fixtures__/export';
import { pointSourceRecord } from '$lib/fetch/extrasolar/__fixtures__/record';
import type { ColumnSpec } from '$lib/fetch/extrasolar/__fixtures__/writer';
import { ltrIsolate } from '$lib/format/bidi';
import { starSections, starStats } from './star-rows';

/** The text without its bidi isolates and with plain spaces. */
const ISOLATES = new RegExp('[\\u2066-\\u2069]', 'g');
const NO_BREAK = new RegExp('\\u00a0', 'g');
const plain = (s: string) => s.replace(ISOLATES, '').replace(NO_BREAK, ' ');

describe.skipIf(!HAS_EXPORT)("a star's panel rows from its records", () => {
	const lookup = new ExtrasolarLookup(diskSource());
	const record = async (id: number): Promise<ExtrasolarRecord> => {
		const result = await lookup.lookup(id);
		if (result.kind !== 'live') throw new Error(`${id} not found`);
		return result.record;
	};
	const rowsOf = (r: ExtrasolarRecord) =>
		Object.fromEntries(
			starSections(r).map((s) => [
				s.key,
				Object.fromEntries(s.rows.map((x) => [x.label, plain(x.value)]))
			])
		);

	it('shows Sirius from Hipparcos, in V, with no Gaia sections', async () => {
		const sirius = await record(22137869);
		const stats = starStats(sirius).map((row) => row.map((s) => [s.label, s.value, s.note]));
		expect(stats).toEqual([
			[
				['Distance', '2.64 pc', '8.6 ly'],
				['Spectral type', ltrIsolate('A0m...'), undefined]
			],
			[
				['Apparent magnitude', '-1.44', 'V'],
				['Absolute magnitude', (-1.44 + 5 * Math.log10(379.21) - 10).toFixed(2), 'V']
			]
		]);
		const rows = rowsOf(sirius);
		expect(Object.keys(rows)).toEqual(['identifiers', 'position', 'brightness']);
		expect(rows.identifiers).toMatchObject({
			HD: '48915',
			HIP: '32349',
			'IAU name': 'Sirius',
			'Space Map ID': '22137869'
		});
		expect(rows.position).toMatchObject({
			Parallax: '379.2 ± 1.6 mas',
			Distance: '2.637 ± 0.011 pc',
			Epoch: 'J1991.25',
			Astrometry: 'Hipparcos (2007)'
		});
		// The spectral type is an LTR isolate, so in RTL its trailing dots stay at its end.
		const brightness = starSections(sirius).find((s) => s.key === 'brightness');
		expect(brightness?.rows.find((r) => r.label === 'Spectral type')?.value).toBe(
			ltrIsolate('A0m...')
		);
		// No Gaia colour: the tree's estimate from V − I is not shown as one.
		expect(rows.brightness['Colour (BP − RP)']).toBeUndefined();
		expect(rows.brightness['Colour (V − I)']).toBe('-0.02');
		const hd = starSections(sirius)[0].rows.find((r) => r.label === 'HD');
		expect(hd?.href).toBe('https://simbad.cds.unistra.fr/simbad/sim-id?Ident=HD%2048915');
	});

	it('shows Proxima Centauri from Gaia, with every section and its errors', async () => {
		const proxima = await record(27424668);
		expect(
			starStats(proxima)
				.flat()
				.map((s) => s.label)
		).toEqual(['Distance', 'Temperature', 'Apparent magnitude', 'Absolute magnitude']);
		const rows = rowsOf(proxima);
		expect(Object.keys(rows)).toEqual([
			'identifiers',
			'position',
			'brightness',
			'parameters',
			'quality'
		]);
		// Its Wikidata item is in the links section, not here.
		expect(Object.keys(rows.identifiers)).toEqual(['Gaia DR3', 'HIP', 'IAU name', 'Space Map ID']);
		expect(rows.position.Parallax).toBe('768.067 ± 0.050 mas');
		expect(rows.position['Right ascension']).toMatch(/^14ʰ 29ᵐ 34\.\d+ˢ ± 0\.024 mas$/);
		expect(rows.position['Radial velocity']).toBe('-21.94 ± 0.22 km/s');
		expect(rows.brightness['Gaia G']).toMatch(/^8\.98\d* ± 0\.000\d+$/);
		expect(rows.quality.RUWE).toMatch(/^\d\.\d{3}$/);
		expect(rows.quality['Probability: quasar']).toMatch(/^(< )?\d/);
	});

	it('keeps the stat cards even: a lone card stands, an odd third goes', async () => {
		// A Gaia star with no G: the distance alone.
		const noG = await record(22039056063);
		expect(
			starStats(noG)
				.flat()
				.map((s) => s.label)
		).toEqual(['Distance']);
	});
});

describe('the metallicity row', () => {
	const gspphot: ColumnSpec[] = [
		{ name: 'mh_gspphot', type: 'float32', values: [-0.8] },
		{ name: 'mh_gspphot_lower', type: 'float32', values: [-0.9] },
		{ name: 'mh_gspphot_upper', type: 'float32', values: [-0.7] }
	];
	/** A G star of the main sequence, inside every cut of Andrae et al. 2023. */
	const star = {
		mh_xgboost: -0.256,
		phot_g_mean_mag: 12,
		phot_bp_mean_mag: 12.4,
		phot_rp_mean_mag: 11.5,
		in_vetted_rgb_sample: false,
		in_oba_golden_sample: false
	};
	type Star = { [K in keyof typeof star]: (typeof star)[K] | null };
	const columns = (values: Partial<Star>): ColumnSpec[] => [
		...gspphot,
		...Object.entries({ ...star, ...values }).map(
			([name, value]): ColumnSpec => ({
				name,
				type: typeof star[name as keyof typeof star] === 'boolean' ? 'bool' : 'float32',
				values: [value]
			})
		)
	];
	const parameter = (r: ExtrasolarRecord, label: string) =>
		plain(
			starSections(r)
				.find((s) => s.key === 'parameters')
				?.rows.find((x) => x.label === label)?.value ?? ''
		);
	const metallicity = (r: ExtrasolarRecord) => parameter(r, 'Metallicity [M/H]');
	const source = (values: Partial<Star> = {}) =>
		parameter(pointSourceRecord(columns(values)), 'Metallicity source');
	const shown = (values: Partial<Star> = {}) => metallicity(pointSourceRecord(columns(values)));
	const XP = '-0.26 dex';
	const GSP_PHOT = '-0.80 ± 0.10 dex';

	it('shows the XP value inside the cuts', () => {
		expect(shown()).toBe(XP);
		expect(shown({ phot_g_mean_mag: 17.65 })).toBe(XP);
	});

	it('falls back to GSP-Phot outside the colour range', () => {
		expect(shown({ phot_bp_mean_mag: 11.9 })).toBe(GSP_PHOT);
		expect(shown({ phot_bp_mean_mag: 14.0 })).toBe(GSP_PHOT);
		expect(shown({ phot_bp_mean_mag: null })).toBe(GSP_PHOT);
	});

	it('falls back for a faint star, an OBA star or no OBA flag', () => {
		expect(shown({ phot_g_mean_mag: 17.7 })).toBe(GSP_PHOT);
		expect(shown({ in_oba_golden_sample: true })).toBe(GSP_PHOT);
		expect(shown({ in_oba_golden_sample: null })).toBe(GSP_PHOT);
	});

	it('trusts a vetted red giant outside the colour range', () => {
		expect(shown({ phot_bp_mean_mag: 14.6, in_vetted_rgb_sample: true })).toBe(XP);
	});

	it('names the source of the value it shows', () => {
		expect(source()).toBe('Gaia XP (Andrae et al. 2023)');
		expect(source({ in_oba_golden_sample: true })).toBe('Gaia DR3 GSP-Phot');
		expect(source({ mh_xgboost: null })).toBe('Gaia DR3 GSP-Phot');
	});

	it('falls back without an XP value', () => {
		expect(shown({ mh_xgboost: null })).toBe(GSP_PHOT);
		// An export from before the XP columns.
		expect(metallicity(pointSourceRecord(gspphot))).toBe(GSP_PHOT);
	});

	it('names the quantity of the value it shows', () => {
		const pastel = pointSourceRecord([
			...gspphot,
			{ name: 'feh_pastel', type: 'float32', values: [-0.1] }
		]);
		expect(parameter(pastel, 'Metallicity [Fe/H]')).toBe('-0.10 dex');
		expect(parameter(pastel, 'Metallicity [M/H]')).toBe('');
		expect(parameter(pastel, 'Metallicity source')).toBe('PASTEL (Soubiran et al. 2016)');
	});

	it('leaves the row out with neither', () => {
		const none = pointSourceRecord([{ name: 'parallax', type: 'float32', values: [10] }]);
		expect(metallicity(none)).toBe('');
		expect(parameter(none, 'Metallicity source')).toBe('');
	});
});

describe('the identifiers of the metallicity catalogues', () => {
	const identifiers = (r: ExtrasolarRecord) =>
		starSections(r)[0].rows.map((x) => [x.label, x.value, x.href]);

	it('reads them from the Point source row', () => {
		const record = pointSourceRecord([
			{ name: 'pastel_designation', type: 'string', values: ['HD 4'] },
			{ name: 'apogee_id', type: 'string', values: ['2M03003170+0008161'] },
			{ name: 'lamost_id', type: 'string', values: ['J112838.67+551809.8'] }
		]);
		expect(identifiers(record)).toEqual([
			['PASTEL', 'HD 4', undefined],
			['APOGEE DR17', '2M03003170+0008161', undefined],
			['LAMOST DR10', 'J112838.67+551809.8', undefined],
			['Space Map ID', '1', undefined]
		]);
	});

	it('leaves out the ones the row does not have', () => {
		const record = pointSourceRecord([
			{ name: 'pastel_designation', type: 'string', values: [null] },
			{ name: 'apogee_id', type: 'string', values: ['2M1'] }
		]);
		expect(identifiers(record)).toEqual([
			['APOGEE DR17', '2M1', undefined],
			['Space Map ID', '1', undefined]
		]);
	});
});
