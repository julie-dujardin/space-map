import { describe, expect, it } from 'vitest';
import { ExtrasolarLookup, type ExtrasolarRecord } from '$lib/fetch/extrasolar/lookup';
import { HAS_EXPORT, diskSource } from '$lib/fetch/extrasolar/__fixtures__/export';
import { pointSourceRecord, valueColumns } from '$lib/fetch/extrasolar/__fixtures__/record';
import type { ColumnSpec } from '$lib/fetch/extrasolar/__fixtures__/writer';
import { STAR } from '$lib/fetch/extrasolar/__fixtures__/synthetic';
import { ltrIsolate } from '$lib/format/bidi';
import { starSections, starStats } from './star-rows';

/** The text without its bidi isolates and with plain spaces. */
const ISOLATES = new RegExp('[\\u2066-\\u2069]', 'g');
const NO_BREAK = new RegExp('\\u00a0', 'g');
const plain = (s: string) => s.replace(ISOLATES, '').replace(NO_BREAK, ' ');

describe("a star's distance", () => {
	const UNCERTAIN =
		'Uncertain. This star has no reliable parallax, so the distance comes from another source.';
	const record = (values: Record<string, number | string>) =>
		pointSourceRecord(valueColumns(values));
	const position = (r: ExtrasolarRecord) =>
		starSections(r).find((s) => s.key === 'position')?.rows ?? [];

	it('comes from the distance group where the parallax is under 5σ', () => {
		const star = record({
			parallax: 0.012,
			parallax_error: 0.02,
			distance: 6267,
			distance_lower: 4826,
			distance_upper: 8535,
			distance_source: 'bailer-jones-2021',
			teff_gspphot: 5000,
			phot_g_mean_mag: 12
		});
		const cards = starStats(star).flat();
		expect(cards.map((s) => [s.label, plain(s.value), s.tooltip])).toEqual([
			['Distance', '6,270 pc', UNCERTAIN],
			['Temperature', expect.any(String), undefined],
			['Apparent magnitude', '12.00', undefined],
			['Absolute magnitude', (12 - 5 * Math.log10(6267) + 5).toFixed(2), UNCERTAIN]
		]);
		const rows = position(star);
		const distance = rows.find((r) => r.label === 'Distance');
		expect(plain(distance!.value)).toBe('6,267 pc (4,826–8,535 pc)');
		expect(distance!.tooltip).toBe(UNCERTAIN);
		expect(rows.find((r) => r.label === 'Distance source')?.value).toBe('Bailer-Jones et al. 2021');
	});

	it('comes from a 5σ parallax before the distance group', () => {
		const star = record({
			parallax: 500,
			parallax_error: 0.1,
			distance: 2.5,
			distance_source: 'reyle-2021'
		});
		expect(starStats(star)[0][0].tooltip).toBeUndefined();
		const rows = position(star);
		expect(plain(rows.find((r) => r.label === 'Distance')!.value)).toBe('2.00000 ± 0.00040 pc');
		expect(rows.find((r) => r.label === 'Distance')!.tooltip).toBeUndefined();
		expect(rows.find((r) => r.label === 'Distance source')).toBeUndefined();
	});

	it('marks a parallax under 0.5 fidelity, where the group has no value', () => {
		const star = record({
			parallax: 10,
			parallax_error: 0.1,
			astrometry_source: 'gaia-dr3',
			fidelity_v2: 0.1,
			hipparcos_photometry_source: 'hipparcos-2007'
		});
		const distance = position(star).find((r) => r.label === 'Distance');
		expect(distance?.tooltip).toBe('Uncertain. The astrometry of this star may be spurious.');
		expect(position(star).find((r) => r.label === 'Distance source')).toBeUndefined();
	});

	it('shows the value alone where the group has no bounds', () => {
		const star = record({ distance: 1.994, distance_source: 'reyle-2021' });
		expect(plain(position(star).find((r) => r.label === 'Distance')!.value)).toBe('1.99 pc');
	});

	it('rounds a distance with one bound as its card does', () => {
		const star = record({ distance: 2350, distance_upper: 2400, distance_source: 'literature' });
		expect(plain(position(star).find((r) => r.label === 'Distance')!.value)).toBe('2,350 pc');
	});

	it('trusts a 5σ SIMBAD parallax and names SIMBAD', () => {
		const star = record({
			parallax: 0.1,
			parallax_error: 0.2,
			distance: 500,
			distance_lower: 476,
			distance_upper: 526,
			distance_source: 'simbad-parallax'
		});
		const rows = position(star);
		expect(rows.find((r) => r.label === 'Distance')!.tooltip).toBeUndefined();
		expect(rows.find((r) => r.label === 'Distance source')?.value).toBe('SIMBAD');
	});

	it('shows the magnitudes of a star that only SIMBAD measured', () => {
		const star = record({
			simbad_v_mag: 7,
			sp_type: 'K0',
			distance: 100,
			distance_source: 'reyle-2021'
		});
		const cards = starStats(star).flat().slice(2);
		expect(cards.map((s) => [s.label, plain(s.value), s.note])).toEqual([
			['Apparent magnitude', '7.00', 'V'],
			['Absolute magnitude', '2.00', 'V']
		]);
	});

	it('names the paper of a distance from the literature table', () => {
		const star = record({
			distance: 2350,
			distance_lower: 2300,
			distance_upper: 2400,
			distance_method: 'expansion',
			distance_source: 'literature'
		});
		const smith = { short: 'Smith 2006', title: 'The Homunculus', url: 'https://doi.org/x' };
		const rows = starSections(star, { distance: [smith] }).find((s) => s.key === 'position')!.rows;
		const distance = rows.find((r) => r.label === 'Distance')!;
		expect(plain(distance.value)).toBe('2,350 ± 50 pc');
		// A paper's distance was chosen for the star, so it is not marked uncertain.
		expect(distance.tooltip).toBeUndefined();
		expect(rows.filter((r) => r.label === 'Distance source')).toEqual([
			{ label: 'Distance source', value: 'Smith 2006', href: 'https://doi.org/x' }
		]);
		// Before the object entry loads.
		expect(position(star).find((r) => r.label === 'Distance source')?.value).toBe(
			'Published paper'
		);
	});
});

describe("a star's identifiers", () => {
	it('leaves out the SIMBAD oid and the literature key', () => {
		const star: ExtrasolarRecord = {
			id: STAR,
			metadata: {
				id: STAR,
				name: 'Westerlund 1 W 26',
				nameSource: 'simbad',
				class: 'star',
				classSource: null,
				crossIds: [
					{ catalogue: 'gaia', release: 'dr3', catalogueId: '5940106041452150272' },
					{ catalogue: 'simbad', release: 'oid', catalogueId: '3521966' },
					{
						catalogue: 'literature',
						release: 'star',
						catalogueId: 'gaia/dr3/5940106041452150272'
					}
				],
				mask: 2,
				object: false,
				aliasTarget: null
			},
			rows: new Map(),
			home: null,
			credits: []
		};
		const identifiers = starSections(star).find((s) => s.key === 'identifiers')!.rows;
		expect(identifiers.map((r) => [r.label, r.value])).toEqual([
			['Gaia DR3', '5940106041452150272'],
			['Space Map ID', String(STAR)]
		]);
	});
});

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
		expect(Object.keys(rows)).toEqual(['identifiers', 'position', 'brightness', 'parameters']);
		expect(rows.parameters['Metallicity source']).toBe('PASTEL (Soubiran et al. 2016)');
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
		).toEqual([
			'Distance',
			'Temperature',
			'Apparent magnitude',
			'Absolute magnitude',
			'Radius',
			'Luminosity'
		]);
		const rows = rowsOf(proxima);
		expect(Object.keys(rows)).toEqual([
			'identifiers',
			'position',
			'brightness',
			'physical',
			'parameters',
			'quality'
		]);
		// Its Wikidata item is in the links section, and the planet catalogues'
		// keys are not shown.
		expect(Object.keys(rows.identifiers)).toEqual([
			'Gaia DR3',
			'HIP',
			'IAU name',
			'PASTEL',
			'Space Map ID'
		]);
		expect(rows.position.Parallax).toBe('768.067 ± 0.050 mas');
		expect(rows.position['Right ascension']).toMatch(/^14ʰ 29ᵐ 34\.\d+ˢ ± 0\.024 mas$/);
		expect(rows.position['Radial velocity']).toBe('-21.94 ± 0.22 km/s');
		expect(rows.brightness['Gaia G']).toMatch(/^8\.98\d* ± 0\.000\d+$/);
		expect(rows.quality.RUWE).toMatch(/^\d\.\d{3}$/);
		// FLAME fits its radius from the parallax, and gives it no mass.
		expect(rows.physical.Radius).toMatch(/^0\.16\d+ ± 0\.00\d+ R☉$/);
		expect(rows.physical.Mass).toBeUndefined();
		expect(rows.physical['Distance used']).toBe('Parallax');
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

describe("a binary star's distance", () => {
	const star = (parallax: number, error: number): ColumnSpec[] => [
		{ name: 'ra', type: 'float64', values: [45] },
		{ name: 'dec', type: 'float64', values: [30] },
		{ name: 'parallax', type: 'float32', values: [parallax] },
		{ name: 'parallax_error', type: 'float32', values: [error] },
		{ name: 'phot_g_mean_mag', type: 'float32', values: [8] },
		{ name: 'astrometry_source', type: 'dict', values: ['gaia-dr3'] }
	];
	const orbit = (type: string): ColumnSpec[] => [
		{ name: 'nss_solution_type', type: 'dict', values: [type] },
		{ name: 'parallax_nss', type: 'float32', values: [12.5] },
		{ name: 'parallax_nss_error', type: 'float32', values: [0.0625] },
		{ name: 'orbit_source', type: 'dict', values: ['gaia-dr3'] }
	];
	const position = (record: ExtrasolarRecord) =>
		Object.fromEntries(
			starSections(record)
				.find((s) => s.key === 'position')!
				.rows.map((x) => [x.label, plain(x.value)])
		);
	const stats = (record: ExtrasolarRecord) =>
		starStats(record).map((row) => row.map((s) => [s.label, s.value, s.note]));

	it('shows the parallax of an astrometric orbit solution and names it', () => {
		const binary = pointSourceRecord(star(10, 0.125), [], orbit('Orbital'));
		// The same as a single star with the orbit's parallax.
		const same = pointSourceRecord(star(12.5, 0.0625));
		expect(stats(binary)).toEqual(stats(same));
		const rows = position(binary);
		const expected = position(same);
		expect(rows.Parallax).toBe(expected.Parallax);
		expect(rows.Distance).toBe(expected.Distance);
		expect(rows.Astrometry).toBe('Gaia DR3, parallax from Gaia DR3 orbit solution');
		expect(expected.Astrometry).toBe('Gaia DR3');
	});

	it('keeps the single-star parallax beside a spectroscopic solution', () => {
		const binary = pointSourceRecord(star(10, 0.125), [], orbit('SB1'));
		const single = pointSourceRecord(star(10, 0.125));
		expect(stats(binary)).toEqual(stats(single));
		expect(position(binary)).toEqual(position(single));
	});

	it("names the orbit parallax that places a planet host by its catalogue's distance", () => {
		const host: ColumnSpec[] = [
			...star(0.5, 0.125),
			{ name: 'host_distance', type: 'float32', values: [70] },
			{ name: 'host_star_source', type: 'dict', values: ['nasa-exoplanet-archive'] }
		];
		const rows = position(pointSourceRecord(host, [], orbit('Orbital')));
		expect(rows.Parallax).toBe(position(pointSourceRecord(star(12.5, 0.0625))).Parallax);
		expect(rows.Astrometry).toBe('Gaia DR3, parallax from Gaia DR3 orbit solution');
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

/** A record with one Point source row of these columns and nothing else. */
function synthetic(
	values: Record<string, number | string | null>,
	orbit?: ColumnSpec[]
): ExtrasolarRecord {
	return pointSourceRecord(
		Object.entries(values).map(([name, value]) => ({
			name,
			type: typeof value === 'string' ? 'string' : 'float32',
			values: [value]
		})),
		[],
		orbit
	);
}

describe("a star's FLAME values", () => {
	const dwarf = {
		parallax: 100,
		parallax_error: 0.1,
		phot_g_mean_mag: 5,
		teff_gspphot: 5600,
		radius_gspphot: 0.8,
		radius_flame: 0.9,
		radius_flame_lower: 0.88,
		radius_flame_upper: 0.92,
		lum_flame: 0.75,
		mass_flame: 0.95,
		mass_flame_lower: 0.9,
		mass_flame_upper: 1.02,
		age_flame: 4.5,
		age_flame_lower: 2,
		age_flame_upper: 8,
		evolstage_flame: 250,
		gravredshift_flame: 0.67,
		bc_flame: -0.05,
		flags_flame: '00'
	};
	const physical = (values: Record<string, number | string | null>) =>
		Object.fromEntries(
			(starSections(synthetic(values)).find((s) => s.key === 'physical')?.rows ?? []).map((r) => [
				r.label,
				plain(r.value)
			])
		);
	const cards = (values: Record<string, number | string | null>) =>
		starStats(synthetic(values))
			.flat()
			.map((s) => [s.label, plain(s.value)]);

	it("shows a dwarf's whole fit, and draws its radius from FLAME", () => {
		expect(physical(dwarf)).toEqual({
			Radius: '0.900 ± 0.020 R☉',
			Luminosity: '0.75 L☉',
			Mass: '0.950 M☉ (0.900–1.020 M☉)',
			Age: '4.5 Ga (2.0–8.0 Ga)',
			'Evolutionary stage': 'Main sequence',
			'Gravitational redshift': '0.67 km/s',
			'Bolometric correction': '-0.05',
			'Distance used': 'Parallax'
		});
		expect(cards(dwarf).slice(-2)).toEqual([
			['Radius', '0.9 R☉'],
			['Mass', '0.95 M☉']
		]);
		const parameters = starSections(synthetic(dwarf)).find((s) => s.key === 'parameters');
		expect(parameters?.rows.find((r) => r.label === 'Radius from photometry')?.value).toBe(
			'0.80 R☉'
		);
	});

	it("drops a giant's mass, age and stage outside 1 to 2 solar masses", () => {
		const giant = { ...dwarf, mass_flame: 3, evolstage_flame: 600, flags_flame: '10' };
		expect(Object.keys(physical(giant))).toEqual([
			'Radius',
			'Luminosity',
			'Gravitational redshift',
			'Bolometric correction',
			'Distance used'
		]);
		expect(cards(giant).at(-1)).toEqual(['Luminosity', '0.75 L☉']);
		const kept = physical({ ...giant, mass_flame: 1.5, flags_flame: '11' });
		expect(kept['Evolutionary stage']).toBe('Red giant');
		expect(kept['Distance used']).toBe('Distance from photometry');
	});

	it.each([
		[389, 'Main sequence'],
		[390, 'Main-sequence turn-off'],
		[420, 'Subgiant'],
		[489, 'Subgiant'],
		[490, 'Red giant']
	])('names stage %i %s', (stage, name) => {
		expect(physical({ ...dwarf, evolstage_flame: stage })['Evolutionary stage']).toBe(name);
	});

	it('shows the run on GSP-Spec in its own section, with the same giant rule', () => {
		const spec = {
			...dwarf,
			radius_flame_spec: 0.95,
			lum_flame_spec: 0.8,
			mass_flame_spec: 0.97,
			age_flame_spec: 3.9,
			evolstage_flame_spec: 300,
			bc_flame_spec: -0.04,
			flags_flame_spec: '0'
		};
		const section = (values: Record<string, number | string | null>) =>
			Object.fromEntries(
				(starSections(synthetic(values)).find((s) => s.key === 'physical_spec')?.rows ?? []).map(
					(r) => [r.label, plain(r.value)]
				)
			);
		expect(section(spec)).toEqual({
			Radius: '0.95 R☉',
			Luminosity: '0.80 L☉',
			Mass: '0.97 M☉',
			Age: '3.90 Ga',
			'Evolutionary stage': 'Main sequence',
			'Bolometric correction': '-0.04'
		});
		const giant = section({ ...spec, mass_flame_spec: 2.5, flags_flame_spec: '1' });
		expect(giant.Mass).toBeUndefined();
		expect(giant.Age).toBeUndefined();
		// The run on GSP-Phot keeps its own values.
		expect(physical(spec).Mass).toBe('0.950 M☉ (0.900–1.020 M☉)');
		expect(section(dwarf)).toEqual({});
	});

	it('shows no stage where FLAME fitted no mass', () => {
		const noMass = { ...dwarf, mass_flame: null, age_flame: null, flags_flame: '20' };
		expect(physical(noMass)['Evolutionary stage']).toBeUndefined();
		const spec = { ...dwarf, evolstage_flame_spec: 0, flags_flame_spec: '2', lum_flame_spec: 1 };
		const rows = starSections(synthetic(spec)).find((s) => s.key === 'physical_spec')?.rows;
		expect(rows?.map((r) => r.label)).toEqual(['Luminosity']);
	});

	it("names the single-star parallax where an orbit gives the star's own", () => {
		const orbit: ColumnSpec[] = [
			{ name: 'nss_solution_type', type: 'dict', values: ['Orbital'] },
			{ name: 'parallax_nss', type: 'float32', values: [99] },
			{ name: 'parallax_nss_error', type: 'float32', values: [0.5] }
		];
		const section = starSections(synthetic(dwarf, orbit)).find((s) => s.key === 'physical');
		expect(section?.rows.find((r) => r.label === 'Distance used')?.value).toBe(
			'Single-star parallax'
		);
	});

	it('leaves the section out without FLAME, and the lone radius card by the even rule', () => {
		const plainStar = Object.fromEntries(
			Object.entries(dwarf).filter(([name]) => !name.includes('_flame'))
		);
		expect(physical(plainStar)).toEqual({});
		expect(cards(plainStar).map(([label]) => label)).toEqual([
			'Distance',
			'Temperature',
			'Apparent magnitude',
			'Absolute magnitude'
		]);
	});
});
