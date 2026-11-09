import { describe, expect, it } from 'vitest';
import { ExtrasolarLookup, type ExtrasolarRecord } from '$lib/fetch/extrasolar/lookup';
import { HAS_EXPORT, diskSource } from '$lib/fetch/extrasolar/__fixtures__/export';
import {
	SURFACE_STARS,
	pointSourceRecord,
	valueColumns
} from '$lib/fetch/extrasolar/__fixtures__/record';
import type { StarInterior } from '$lib/fetch/extrasolar/interior';
import type { InteriorBlock } from '$lib/fetch/objects/object-data';
import type { ColumnSpec } from '$lib/fetch/extrasolar/__fixtures__/writer';
import type { StarRadius } from '$lib/fetch/extrasolar/lookup';
import { STAR } from '$lib/fetch/extrasolar/__fixtures__/synthetic';
import { ltrIsolate } from '$lib/format/bidi';
import {
	meanDensityRow,
	starAliases,
	starClassLabel,
	starIdentifiers,
	starSections,
	starStats
} from './star-rows';

/** The text without its bidi isolates and with plain spaces. */
const INVISIBLES = new RegExp('[\\u2060\\u2066-\\u2069]', 'g');
const NO_BREAK = new RegExp('\\u00a0', 'g');
const plain = (s: string) => s.replace(INVISIBLES, '').replace(NO_BREAK, ' ');

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
			teff: 5000,
			phot_g_mean_mag: 12
		});
		const cards = starStats(star).flat();
		expect(cards.map((s) => [s.label, plain(s.value), s.tooltip])).toEqual([
			['Distance', '20,400 ly', UNCERTAIN],
			['Temperature', expect.any(String), undefined]
		]);
		const rows = position(star);
		const distance = rows.find((r) => r.label === 'Distance');
		expect(plain(distance!.value)).toBe('20,440 ly (15,740–27,837 ly)');
		expect(distance!.tooltip).toBe(UNCERTAIN);
		expect(rows.find((r) => r.label === 'Distance source')).toBeUndefined();
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
		expect(plain(rows.find((r) => r.label === 'Distance')!.value)).toBe('6.5231 ± 0.0013 ly');
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
		expect(plain(position(star).find((r) => r.label === 'Distance')!.value)).toBe('6.5 ly');
	});

	it('rounds a distance with one bound as its card does', () => {
		const star = record({ distance: 2350, distance_upper: 2400, distance_source: 'literature' });
		expect(plain(position(star).find((r) => r.label === 'Distance')!.value)).toBe('7,660 ly');
	});

	it("says that a distance is its star system's, and keeps the parallax of the star", () => {
		const star = record({
			parallax: 100,
			parallax_error: 1,
			distance: 9.5,
			distance_lower: 9.4,
			distance_upper: 9.6,
			distance_method: 'system',
			distance_source: 'star-systems'
		});
		const [card] = starStats(star).flat();
		expect([card.label, plain(card.value), card.tooltip, card.note]).toEqual([
			'Distance',
			'31 ly',
			undefined,
			undefined
		]);
		const rows = position(star);
		const distance = rows.find((r) => r.label === 'Distance')!;
		expect(plain(distance.value)).toBe('30.98 ± 0.33 ly');
		expect([distance.tooltip, distance.note]).toEqual([undefined, 'from its star system']);
		expect(plain(rows.find((r) => r.label === 'Parallax')!.value)).toBe('100.0 ± 1.0 mas');
	});

	it('trusts a 5σ SIMBAD parallax without a provenance row', () => {
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
		expect(rows.find((r) => r.label === 'Distance source')).toBeUndefined();
	});

	it('drops magnitudes from the stat bar', () => {
		const star = record({
			simbad_v_mag: 7,
			distance: 100,
			distance_source: 'reyle-2021'
		});
		star.metadata.spectralType = 'K0';
		const cards = starStats(star).flat();
		expect(cards.map((s) => [s.label, plain(s.value)])).toEqual([
			['Distance', '326 ly'],
			['Spectral type', 'K0']
		]);
	});

	it('leaves distance provenance to the credits', () => {
		const star = record({
			distance: 2350,
			distance_lower: 2300,
			distance_upper: 2400,
			distance_method: 'expansion',
			distance_source: 'literature'
		});
		const rows = starSections(star).find((s) => s.key === 'position')!.rows;
		const distance = rows.find((r) => r.label === 'Distance')!;
		expect(plain(distance.value)).toBe('7,665 ± 163 ly');
		// A paper's distance was chosen for the star, so it is not marked uncertain.
		expect(distance.tooltip).toBeUndefined();
		expect(rows.filter((r) => r.label === 'Distance source')).toEqual([]);
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
				system: null,
				families: 0n,
				familiesEstimated: 0n,
				radius: null,
				spectralType: null,
				object: false,
				aliasTarget: null
			},
			rows: new Map(),
			home: null,
			credits: []
		};
		const identifiers = starIdentifiers(star);
		expect(identifiers.map((r) => [r.label, r.value])).toEqual([
			['Gaia DR3', '5940106041452150272']
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
		expect(stats[0].slice(0, 2)).toEqual([
			['Diameter', '2.35M km', undefined],
			['Distance', '8.61 ly', undefined]
		]);
		// Flower's Teff from the Hipparcos B − V.
		expect(stats[0][2]).toEqual(['Temperature', '9,132 °C', 'estimated']);
		const rows = rowsOf(sirius);
		// No mass: the Interior section has nothing to show.
		expect(Object.keys(rows)).toEqual(['classification', 'atmosphere', 'surface', 'position']);
		expect(rows.atmosphere['Metallicity source']).toBeUndefined();
		expect(
			Object.fromEntries(starIdentifiers(sirius).map((x) => [x.label, x.value]))
		).toMatchObject({
			HD: '48915',
			HIP: '32349',
			'IAU name': 'Sirius'
		});
		// Bond et al. 2017's parallax gives the distance. The parallax row is Hipparcos's.
		expect(rows.position).toMatchObject({
			Parallax: '379.2 ± 1.6 mas',
			Distance: '8.608 ± 0.032 ly',
			Epoch: 'J1991.25'
		});
		// SIMBAD's type, which gives the families, as an LTR isolate for RTL text.
		const classification = starSections(sirius).find((s) => s.key === 'classification');
		expect(classification?.rows.find((r) => r.label === 'Spectral type')?.value).toBe(
			ltrIsolate('A0mA1Va')
		);
		const hd = starIdentifiers(sirius).find((r) => r.label === 'HD');
		expect(hd?.href).toBe('https://simbad.cds.unistra.fr/simbad/sim-id?Ident=HD%2048915');
	});

	it('shows Sirius B at the distance of its system, with its own parallax', async () => {
		const siriusB = await record(559008781);
		const card = starStats(siriusB)
			.flat()
			.find((s) => s.label === 'Distance');
		expect([card?.value, card?.tooltip, card?.note]).toEqual(['8.61 ly', undefined, undefined]);
		const position = starSections(siriusB).find((s) => s.key === 'position')!.rows;
		const distance = position.find((r) => r.label === 'Distance')!;
		expect([plain(distance.value), distance.note]).toEqual([
			'8.608 ± 0.032 ly',
			'from its star system'
		]);
		expect(plain(position.find((r) => r.label === 'Parallax')!.value)).toBe('374.49 ± 0.23 mas');
	});

	it('shows Proxima Centauri from Gaia, with every section and its errors', async () => {
		const proxima = await record(27424668);
		expect(
			starStats(proxima)
				.flat()
				.map((s) => s.label)
		).toEqual(['Diameter', 'Distance', 'Temperature']);
		const rows = rowsOf(proxima);
		expect(Object.keys(rows)).toEqual([
			'classification',
			'atmosphere',
			'surface',
			'interior',
			'position'
		]);
		// Its Wikidata item is in the links section, and the planet catalogues'
		// keys are not shown.
		expect(starIdentifiers(proxima).map((x) => x.label)).toEqual([
			'Gaia DR3',
			'HIP',
			'IAU name',
			'PASTEL',
			'GCVS'
		]);
		expect(rows.position.Parallax).toBe('768.067 ± 0.050 mas');
		expect(rows.position['Right ascension']).toMatch(/^14ʰ 29ᵐ 34\.\d+ˢ ± 0\.024 mas$/);
		expect(rows.position['Radial velocity']).toBe('-21.94 ± 0.22 km/s');
		// FLAME fits its radius from the parallax and gives it no mass; the planet
		// catalogue does.
		expect(rows.surface.Diameter).toMatch(/^[\d,]+ ± [\d,]+ km$/);
		expect(rows.interior.Mass).toBe('2.428×10²⁹ kg');
		expect(rows.surface['Apparent magnitude (V)']).toBe('11.01');
	});

	it('shows a lone available stat without padding', async () => {
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

	it('shows the parallax of an astrometric orbit solution', () => {
		const binary = pointSourceRecord(star(10, 0.125), [], orbit('Orbital'));
		// The same as a single star with the orbit's parallax.
		const same = pointSourceRecord(star(12.5, 0.0625));
		expect(stats(binary)).toEqual(stats(same));
		const rows = position(binary);
		const expected = position(same);
		expect(rows.Parallax).toBe(expected.Parallax);
		expect(rows.Distance).toBe(expected.Distance);
		expect(rows.Astrometry).toBeUndefined();
		expect(expected.Astrometry).toBeUndefined();
	});

	it('keeps the single-star parallax beside a spectroscopic solution', () => {
		const binary = pointSourceRecord(star(10, 0.125), [], orbit('SB1'));
		const single = pointSourceRecord(star(10, 0.125));
		expect(stats(binary)).toEqual(stats(single));
		expect(position(binary)).toEqual(position(single));
	});

	it("uses the orbit parallax that places a planet host by its catalogue's distance", () => {
		const host: ColumnSpec[] = [
			...star(0.5, 0.125),
			{ name: 'host_distance', type: 'float32', values: [70] },
			{ name: 'host_star_source', type: 'dict', values: ['nasa-exoplanet-archive'] }
		];
		const rows = position(pointSourceRecord(host, [], orbit('Orbital')));
		expect(rows.Parallax).toBe(position(pointSourceRecord(star(12.5, 0.0625))).Parallax);
		expect(rows.Astrometry).toBeUndefined();
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
				.find((s) => s.key === 'atmosphere')
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

	it('leaves the source to the credits', () => {
		expect(source()).toBe('');
		expect(source({ in_oba_golden_sample: true })).toBe('');
		expect(source({ mh_xgboost: null })).toBe('');
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
		expect(parameter(pastel, 'Metallicity source')).toBe('');
	});

	it('leaves the row out with neither', () => {
		const none = pointSourceRecord([{ name: 'parallax', type: 'float32', values: [10] }]);
		expect(metallicity(none)).toBe('');
		expect(parameter(none, 'Metallicity source')).toBe('');
	});
});

describe('the identifiers of the catalogues that join the Point source row', () => {
	const identifiers = (r: ExtrasolarRecord) =>
		starIdentifiers(r).map((x) => [x.label, x.value, x.href]);

	it('reads them from the Point source row', () => {
		const record = pointSourceRecord([
			{ name: 'pastel_designation', type: 'string', values: ['HD 4'] },
			{ name: 'apogee_id', type: 'string', values: ['2M03003170+0008161'] },
			{ name: 'lamost_id', type: 'string', values: ['J112838.67+551809.8'] },
			{ name: 'gcvs_name', type: 'string', values: ['V645 Cen'] },
			{ name: 'atnf_name', type: 'string', values: ['J0146+6145'] },
			{ name: 'spicy_id', type: 'uint32', values: [12345] }
		]);
		expect(identifiers(record)).toEqual([
			['PASTEL', 'HD 4', 'https://simbad.cds.unistra.fr/simbad/sim-id?Ident=HD%204'],
			['APOGEE DR17', '2M03003170+0008161', undefined],
			['LAMOST DR10', 'J112838.67+551809.8', undefined],
			['GCVS', 'V645 Cen', 'https://simbad.cds.unistra.fr/simbad/sim-id?Ident=V*%20V645%20Cen'],
			[
				'ATNF',
				'J0146+6145',
				'https://simbad.cds.unistra.fr/simbad/sim-id?Ident=PSR%20J0146%2B6145'
			],
			['SPICY', '12345', undefined]
		]);
	});

	it("shows a PASTEL designation without SIMBAD's object-type prefix", () => {
		const pastel = (designation: string) =>
			identifiers(
				pointSourceRecord([{ name: 'pastel_designation', type: 'string', values: [designation] }])
			)[0];
		expect(pastel('* alf CMa')).toEqual([
			'PASTEL',
			'alf CMa',
			'https://simbad.cds.unistra.fr/simbad/sim-id?Ident=*%20alf%20CMa'
		]);
		expect(pastel('V* V645 Cen')[1]).toBe('V645 Cen');
		expect(pastel('Cl* Berkeley 18 K 1383')[1]).toBe('Berkeley 18 K 1383');
		expect(pastel('BD+49 435')[1]).toBe('BD+49 435');
	});

	it('leaves out the ones the row does not have', () => {
		const record = pointSourceRecord([
			{ name: 'pastel_designation', type: 'string', values: [null] },
			{ name: 'apogee_id', type: 'string', values: ['2M1'] }
		]);
		expect(identifiers(record)).toEqual([['APOGEE DR17', '2M1', undefined]]);
	});
});

/** A record with one Point source row of these columns, the Metadata
 *  `radius` and nothing else. */
const SYNTHETIC_TYPES = { string: 'string', boolean: 'bool' } as const;

function synthetic(
	values: Record<string, number | string | boolean | null>,
	orbit?: ColumnSpec[],
	radius: StarRadius | null = null
): ExtrasolarRecord {
	return pointSourceRecord(
		Object.entries(values).map(([name, value]) => ({
			name,
			type: SYNTHETIC_TYPES[typeof value as keyof typeof SYNTHETIC_TYPES] ?? 'float32',
			values: [value]
		})),
		[],
		orbit,
		radius
	);
}

type Values = Record<string, number | string | boolean | null>;

describe("a star's diameter", () => {
	const row = (values: Values, radius: StarRadius | null) =>
		starSections(synthetic(values, undefined, radius))
			.find((s) => s.key === 'surface')
			?.rows.find((r) => r.label.startsWith('Diameter'));
	const card = (values: Values, radius: StarRadius | null) =>
		starStats(synthetic(values, undefined, radius))
			.flat()
			.find((s) => s.label === 'Diameter');
	const transitHost = {
		teff_gspphot: 6300,
		radius_literature: 1.5,
		radius_flame: 1.9,
		host_radius: 1.657,
		host_radius_error: 0.046
	};

	it("shows the export's radius and its source, not a column the export passed over", () => {
		const radius = { solar: 1.657, source: 'nasa-exoplanet-archive' } as const;
		const diameter = row(transitHost, radius)!;
		expect(plain(diameter.value)).toBe('2,306,000 ± 64,000 km');
		expect(plain(diameter.tooltip!)).toBe('1.66× the Sun · Source: NASA Exoplanet Archive');
		expect(plain(card(transitHost, radius)!.value)).toBe('2.31M km');
	});

	it('shows a measurement at three figures', () => {
		const diameter = row(transitHost, { solar: 1.5, source: 'literature' })!;
		expect(plain(diameter.value)).toBe('2,090,000 km');
		expect(diameter.tooltip).toContain('Source: Published paper');
		const jmdc = row(transitHost, { solar: 1.5, source: 'jmdc' })!;
		expect(jmdc.tooltip).toContain('Source: JMDC');
	});

	it("gives a FLAME-spec radius the bounds of FLAME's second run", () => {
		const spec = {
			radius_flame_spec: 0.95,
			radius_flame_spec_lower: 0.9,
			radius_flame_spec_upper: 1
		};
		const diameter = row(spec, { solar: 0.95, source: 'gaia-dr3-flame-spec' })!;
		expect(plain(diameter.value)).toBe('1,322,000 ± 70,000 km');
		expect(diameter.tooltip).toContain('Source: Gaia DR3 FLAME (GSP-Spec)');
	});

	it('has no row and no card without a radius, whatever the columns hold', () => {
		expect(row(transitHost, null)).toBeUndefined();
		expect(card(transitHost, null)).toBeUndefined();
	});
});

describe("a star's sections", () => {
	/** The radius that the export picks for these columns (`radius.py`). A
	 *  paper's comes first, then Gaia's fits, which do not hold for a compact star. */
	const radiusOf = (values: Values): StarRadius | null => {
		const paper = values.radius_literature;
		if (typeof paper === 'number') return { solar: paper, source: 'literature' };
		if (values.compact === true) return null;
		const fit = (['', '_spec'] as const).find(
			(run) => typeof values[`radius_flame${run}`] === 'number'
		);
		if (fit !== undefined) {
			const source = fit ? 'gaia-dr3-flame-spec' : 'gaia-dr3-flame';
			return { solar: values[`radius_flame${fit}`] as number, source };
		}
		const gspphot = values.radius_gspphot;
		return typeof gspphot === 'number' ? { solar: gspphot, source: 'gaia-dr3-gspphot' } : null;
	};
	const sections = (values: Values) => starSections(synthetic(values, undefined, radiusOf(values)));
	const section = (values: Values, key: string) =>
		Object.fromEntries(
			(sections(values).find((s) => s.key === key)?.rows ?? []).map((r) => [
				r.label,
				plain(r.value)
			])
		);
	const entry = (values: Values, key: string, label: string) =>
		sections(values)
			.find((s) => s.key === key)
			?.rows.find((r) => r.label === label);
	const cards = (values: Values) =>
		starStats(synthetic(values, undefined, radiusOf(values)))
			.flat()
			.map((s) => [s.label, plain(s.value)]);
	const { flame, proxima, tauCeti, arcturus, whiteDwarf, sampleWhiteDwarf, pulsar, farStar } =
		SURFACE_STARS;

	it('come in the order of the Sun', () => {
		expect(sections(flame).map((s) => s.key)).toEqual([
			'classification',
			'surface',
			'interior',
			'position'
		]);
		const metal = { ...flame, feh_pastel: -0.1 };
		expect(sections(metal).map((s) => s.key)).toEqual([
			'classification',
			'atmosphere',
			'surface',
			'interior',
			'position'
		]);
	});

	it("show a Gaia star's computed values and FLAME's fit", () => {
		expect(section(flame, 'classification')).toEqual({
			'Evolutionary stage': 'Main sequence',
			Age: '4.5 Ga (2.0–8.0 Ga)'
		});
		expect(section(flame, 'surface')).toEqual({
			Diameter: '1,252,000 ± 28,000 km',
			Gravity: '25.6 g (22.8–28.7 g)',
			Luminosity: '(2.871 ± 0.038)×10²⁶ W',
			'Apparent magnitude (V)': '9.50',
			'Absolute magnitude (V)': '9.50',
			'Gravitational redshift': '0.67 km/s'
		});
		expect(section(flame, 'interior')).toEqual({
			Mass: '1.889×10³⁰ kg (1.790–2.028×10³⁰ kg)',
			density: '1.84 g/cm³'
		});
		const gravity = entry(flame, 'surface', 'Gravity')!;
		expect(plain(gravity.tooltip!)).toBe('250 m/s²');
		expect(gravity.definition).toBe('Gravity at the photosphere');
		const luminosity = entry(flame, 'surface', 'Luminosity')!;
		expect(plain(luminosity.tooltip!)).toBe("75% ± 1% of the Sun's");
		expect(luminosity.definition).toBe('Total power radiated by the star across all wavelengths');
		expect(luminosity.note).toBeUndefined();
		expect(entry(flame, 'surface', 'Apparent magnitude (V)')?.tooltip).toBe(
			'Converted from the Gaia G magnitude and the BP − RP colour index'
		);
		expect(entry(flame, 'surface', 'Absolute magnitude (V)')?.tooltip).toBe(
			'From a V magnitude converted from the Gaia G magnitude and the BP − RP colour index'
		);
		expect(plain(entry(flame, 'interior', 'Mass')!.tooltip!)).toBe("95% (90–102%) of the Sun's");
		expect(cards(flame)).toEqual([
			['Diameter', '1.25M km'],
			['Distance', '32.6 ly'],
			['Temperature', expect.any(String)]
		]);
	});

	it('draw the Teff on the scale of the Surface section, with its bounds', () => {
		const surface = sections(flame).find((s) => s.key === 'surface')!;
		expect(surface.rows.map((r) => r.label)).not.toContain('Effective temperature');
		expect(surface.temperature?.temperatures).toEqual({
			readings: [{ part: 'photosphere', kind: 'mean', k: 5600 }],
			origin: 'measured'
		});
		expect(surface.temperature?.valueTooltip).toBeDefined();
		expect(surface.temperature?.estimatedNote).toBeUndefined();
	});

	it("show a red dwarf's catalogue log g and mass", () => {
		expect(section(proxima, 'surface')).toMatchObject({
			Diameter: '196,000 km',
			Gravity: '160 g',
			'Apparent magnitude (V)': '11.13',
			'Absolute magnitude (V)': '15.56'
		});
		expect(entry(proxima, 'surface', 'Apparent magnitude (V)')?.tooltip).toBeUndefined();
		expect(entry(proxima, 'surface', 'Absolute magnitude (V)')?.tooltip).toBeUndefined();
		expect(section(proxima, 'interior')).toEqual({
			Mass: '2.43×10²⁹ kg',
			density: '61.4 g/cm³'
		});
	});

	it('mark a Teff from a colour and a luminosity from a bolometric correction as estimates', () => {
		for (const star of [tauCeti, arcturus]) {
			const surface = sections(star).find((s) => s.key === 'surface')!;
			expect(surface.temperature?.temperatures.origin).toBe('estimated');
			expect(surface.temperature?.estimatedNote).toBe('Estimated from the B − V colour index.');
			expect(surface.rows.find((r) => r.label === 'Gravity')).toBeUndefined();
		}
		expect(entry(tauCeti, 'surface', 'Luminosity')?.note).toBeUndefined();
		expect(entry(arcturus, 'surface', 'Luminosity')?.note).toBe('estimated');
		expect(section(tauCeti, 'surface').Diameter).toBe('1,100,000 km');
		// No mass, so no density: the section has nothing to show.
		expect(sections(tauCeti).find((s) => s.key === 'interior')).toBeUndefined();
	});

	it('mark the cards of an estimated Teff and luminosity', () => {
		const notes = (values: Values) =>
			starStats(synthetic(values, undefined, radiusOf(values)))
				.flat()
				.map((s) => [s.label, s.note]);
		expect(notes(arcturus)).toEqual([
			['Distance', undefined],
			['Temperature', 'estimated'],
			['Luminosity', 'estimated']
		]);
		expect(notes(flame)[2]).toEqual(['Temperature', undefined]);
	});

	it('say what an absolute V without an extinction rests on', () => {
		expect(entry(farStar, 'surface', 'Absolute magnitude (V)')?.tooltip).toBe(
			'From a V magnitude converted from the Gaia G magnitude and the BP − RP colour index; ' +
				'not corrected for extinction, which is not known for this star'
		);
		const simbadV = { ...farStar, apparent_v_source: 'simbad' };
		expect(entry(simbadV, 'surface', 'Absolute magnitude (V)')?.tooltip).toBe(
			'Not corrected for extinction, which is not known for this star'
		);
		expect(entry(simbadV, 'surface', 'Apparent magnitude (V)')?.tooltip).toBeUndefined();
	});

	it("show a white dwarf's paper values, with their errors", () => {
		expect(section(whiteDwarf, 'surface')).toEqual({
			Diameter: '11,300 km',
			Gravity: '398,000 ± 15,000 g',
			Luminosity: '9.38×10²⁴ W',
			'Apparent magnitude (V)': '8.44',
			'Absolute magnitude (V)': '11.33'
		});
		expect(section(whiteDwarf, 'interior')).toEqual({
			Mass: '(2.024 ± 0.022)×10³⁰ kg',
			density: '2.7×10⁶ g/cm³'
		});
		expect(section(sampleWhiteDwarf, 'interior')).toEqual({ Mass: '(1.193 ± 0.020)×10³⁰ kg' });
		expect(cards(sampleWhiteDwarf).map(([label]) => label)).toEqual([
			'Mass',
			'Distance',
			'Temperature'
		]);
	});

	it("leave out Gaia's main-sequence fits of a white dwarf", () => {
		for (const star of [whiteDwarf, sampleWhiteDwarf]) {
			expect(sections(star).map((s) => s.key)).toEqual(['surface', 'interior', 'position']);
			expect(entry(star, 'surface', 'Gravitational redshift')).toBeUndefined();
		}
		expect(section(sampleWhiteDwarf, 'surface').Diameter).toBeUndefined();
		expect(section(sampleWhiteDwarf, 'surface')['Diameter from photometry']).toBeUndefined();
		// No paper mass: FLAME's mass is a main-sequence fit too.
		const noPaperMass = { ...sampleWhiteDwarf, mass_literature: null };
		expect(sections(noPaperMass).find((s) => s.key === 'interior')).toBeUndefined();
		// The same fits stand for a star that is not compact.
		const notWhiteDwarf = { ...sampleWhiteDwarf, compact: false, mass_literature: null };
		expect(section(notWhiteDwarf, 'surface').Diameter).toBe('626,000 km');
		expect(section(notWhiteDwarf, 'classification').Age).toBe('9.00 Ga');
	});

	it('say when the star formed, at the figures of its age row', () => {
		const tooltip = (values: Values) => plain(entry(values, 'classification', 'Age')!.tooltip!);
		expect(tooltip(flame)).toBe('Formed 4.5 (2.0–8.0) billion years ago');
		const young = { ...flame, age_flame: 0.35, age_flame_lower: 0.2, age_flame_upper: 0.6 };
		expect(section(young, 'classification').Age).toBe('0.35 Ga (0.20–0.60 Ga)');
		expect(tooltip(young)).toBe('Formed 0.35 (0.20–0.60) billion years ago');
		const unbounded = { ...flame, age_flame_lower: null, age_flame_upper: null };
		expect(tooltip(unbounded)).toBe('Formed 4.50 billion years ago');
		expect(tooltip({ ...unbounded, age_flame: 0.9996 })).toBe('Formed 1.00 billion years ago');
		const host = { ...flame, age_flame: null, host_age: 0.4 };
		expect(section(host, 'classification').Age).toBe('0.4 Ga');
		expect(tooltip(host)).toBe('Formed 0.4 billion years ago');
	});

	it('compare a metallicity and a density with the Sun and with materials', () => {
		const metallicity = (values: Values, label: string) =>
			plain(entry(values, 'atmosphere', label)!.tooltip!);
		expect(metallicity({ ...flame, feh_pastel: -0.3 }, 'Metallicity [Fe/H]')).toBe(
			'2× less iron than the Sun'
		);
		expect(metallicity({ ...flame, host_metallicity: 0.2 }, 'Metallicity [Fe/H]')).toBe(
			'1.6× more iron than the Sun'
		);
		expect(plain(entry(flame, 'interior', 'density')!.tooltip!)).toBe('68% of crustal rock');
	});

	it("show a pulsar's mass alone", () => {
		expect(sections(pulsar).map((s) => s.key)).toEqual(['interior', 'position']);
		expect(section(pulsar, 'interior')).toEqual({ Mass: '2.8×10³⁰ kg' });
	});

	it('read a density on its power of ten outside 0.01 to 10,000 g/cm³', () => {
		expect(plain(meanDensityRow(1, 1)!.value)).toBe('1.41 g/cm³');
		expect(plain(meanDensityRow(1.1, 25)!.value)).toBe('9.92×10⁻⁵ g/cm³');
		expect(plain(meanDensityRow(1, 1)!.tooltip!)).toBe('1.41× water');
		expect(plain(meanDensityRow(1.1, 25)!.tooltip!)).toBe('8.1% of sea-level air');
		expect(meanDensityRow(1, null)).toBeNull();
	});

	it('show the centre temperature of an interior, and link to its Structure tab', () => {
		const interior = {
			tier: 1,
			stage: 'main_sequence'
		} as StarInterior;
		const block = {
			layers: [{ role: 'core' }],
			centre_temperature_range_k: [1.4e7, 1.6e7]
		} as InteriorBlock;
		const star = synthetic(flame, undefined, radiusOf(flame));
		const shown = starSections(star, { structure: { interior, block } }).find(
			(s) => s.key === 'interior'
		)!;
		expect(shown.structure).toBe(true);
		expect(shown.rows.map((r) => r.label)).toEqual(['Mass', 'density', 'Core temperature']);
		const rough = starSections(star, { structure: { interior: { ...interior, tier: 3 }, block } });
		expect(rough.find((s) => s.key === 'interior')!.rows.map((r) => r.label)).toEqual([
			'Mass',
			'density'
		]);
		expect(starSections(star).find((s) => s.key === 'interior')!.structure).toBeUndefined();
	});

	it('keep the link to the Structure tab of a star with no interior rows', () => {
		const interior = { tier: 3, stage: 'main_sequence' } as StarInterior;
		const block = { layers: [{ role: 'convective_zone' }] } as InteriorBlock;
		const shown = starSections(synthetic(tauCeti), { structure: { interior, block } }).find(
			(s) => s.key === 'interior'
		);
		expect(shown).toEqual({ key: 'interior', title: 'Interior', rows: [], structure: true });
	});

	it("drops a giant's mass, age and stage outside 1 to 2 solar masses", () => {
		const giant = { ...flame, mass_flame: 3, evolstage_flame: 600, flags_flame: '10' };
		expect(section(giant, 'classification')).toEqual({});
		expect(section(giant, 'interior')).toEqual({});
		expect(cards(giant)[0]).toEqual(['Diameter', '1.25M km']);
		const kept = section({ ...giant, mass_flame: 1.5, flags_flame: '11' }, 'classification');
		expect(kept['Evolutionary stage']).toBe('Red giant');
	});

	it("show a paper's mass before FLAME's, with its bounds", () => {
		const giant = { ...flame, mass_flame: 3, flags_flame: '10', mass_literature: 17.8 };
		expect(section(giant, 'interior').Mass).toBe('3.54×10³¹ kg');
		expect(plain(entry(giant, 'interior', 'Mass')!.tooltip!)).toBe('17.8× the Sun');
		// A 1σ error of 0.06, as the export writes it.
		const sigma = { ...giant, mass_literature: 1.08 };
		const withError = { ...sigma, mass_literature_lower: 1.02, mass_literature_upper: 1.14 };
		expect(section(withError, 'interior').Mass).toBe('(2.15 ± 0.12)×10³⁰ kg');
		expect(plain(entry(withError, 'interior', 'Mass')!.tooltip!)).toBe('(1.08 ± 0.06)× the Sun');
		// Published 68% bounds that are not symmetric.
		const ruchbah = { ...giant, mass_literature: 2.06 };
		const bounds = { ...ruchbah, mass_literature_lower: 1.8, mass_literature_upper: 2.2 };
		expect(section(bounds, 'interior').Mass).toBe('4.10×10³⁰ kg (3.58–4.37×10³⁰ kg)');
		expect(plain(entry(bounds, 'interior', 'Mass')!.tooltip!)).toBe('2.06 (1.80–2.20)× the Sun');
	});

	it.each([
		[389, 'Main sequence'],
		[390, 'Main-sequence turn-off'],
		[420, 'Subgiant'],
		[489, 'Subgiant'],
		[490, 'Red giant']
	])('names stage %i %s', (stage, name) => {
		expect(
			section({ ...flame, evolstage_flame: stage }, 'classification')['Evolutionary stage']
		).toBe(name);
	});

	it('use the spectroscopic fit as a fallback, with the same giant rule', () => {
		const spec = {
			radius_flame_spec: 0.95,
			mass_flame_spec: 0.97,
			age_flame_spec: 3.9,
			evolstage_flame_spec: 300,
			flags_flame_spec: '0'
		};
		expect(section(spec, 'surface')).toEqual({ Diameter: '1,320,000 km' });
		expect(section(spec, 'interior').Mass).toBe('1.93×10³⁰ kg');
		expect(section(spec, 'classification')).toEqual({
			'Evolutionary stage': 'Main sequence',
			Age: '3.90 Ga'
		});
		const giant = { ...spec, mass_flame_spec: 2.5, flags_flame_spec: '1' };
		expect(section(giant, 'interior').Mass).toBeUndefined();
		expect(section(giant, 'classification').Age).toBeUndefined();
	});

	it('show no stage where FLAME fitted no mass', () => {
		const noMass = { ...flame, mass_flame: null, age_flame: null, flags_flame: '20' };
		expect(section(noMass, 'classification')['Evolutionary stage']).toBeUndefined();
	});

	it("do not expose a fit's distance input", () => {
		const orbit: ColumnSpec[] = [
			{ name: 'nss_solution_type', type: 'dict', values: ['Orbital'] },
			{ name: 'parallax_nss', type: 'float32', values: [99] },
			{ name: 'parallax_nss_error', type: 'float32', values: [0.5] }
		];
		const shown = starSections(synthetic(flame, orbit)).flatMap((s) => s.rows);
		expect(shown.find((r) => r.label === 'Distance used')).toBeUndefined();
	});

	it('use the photometric diameter without FLAME and never pad the stat bar', () => {
		const plainStar = {
			...Object.fromEntries(Object.entries(flame).filter(([name]) => !name.includes('_flame'))),
			radius_gspphot: 0.8
		};
		expect(section(plainStar, 'surface')['Diameter from photometry']).toBe('1,110,000 km');
		expect(cards(plainStar).map(([label]) => label)).toEqual([
			'Diameter',
			'Distance',
			'Temperature'
		]);
	});
});

describe("a star's spectral type", () => {
	it('is the type that gives its families, not the Hipparcos one', () => {
		const star = pointSourceRecord(valueColumns({ sp_type: 'M3/M4II:' }));
		star.metadata.spectralType = 'M5Iae';
		const classification = starSections(star).find((s) => s.key === 'classification');
		expect(classification?.rows.find((r) => r.label === 'Spectral type')?.value).toBe(
			ltrIsolate('M5Iae')
		);
	});
});

describe('the class of a star', () => {
	it('names the classes the catalogues give a host', () => {
		expect(starClassLabel('star')).toBe('Star');
		expect(starClassLabel('pulsar')).toBe('Pulsar');
		expect(starClassLabel('white dwarf')).toBe('White dwarf');
		expect(starClassLabel('brown dwarf')).toBe('Brown dwarf');
	});
});

describe.skipIf(!HAS_EXPORT)("a planet host's catalogue rows from the real export", () => {
	it('uses the star values in their corresponding sections', async () => {
		const lookup = new ExtrasolarLookup(diskSource());
		const lich = await lookup.lookup('1634188199');
		if (lich.kind !== 'live') throw new Error('Lich not found');
		const interior = starSections(lich.record).find((section) => section.key === 'interior')!;
		expect(Object.fromEntries(interior.rows.map((x) => [x.label, plain(x.value)]))).toMatchObject({
			// A float32 1.4, at the digits the catalogue gave.
			Mass: '2.8×10³⁰ kg'
		});
		expect(starAliases(lich.record)).not.toContain(lich.record.metadata.name);
	});
});

describe('the links of a star system', () => {
	const withIds = (ids: [string, string, string][]): ExtrasolarRecord => {
		const star = pointSourceRecord([]);
		const crossIds = ids.map(([catalogue, release, catalogueId]) => ({
			catalogue,
			release,
			catalogueId
		}));
		return { ...star, metadata: { ...star.metadata, crossIds } };
	};

	it('hides the claims that key an ID, and names the catalogues', () => {
		const shown = starIdentifiers(
			withIds([
				['star-system', 'member', 'gaia/dr3/2133476355197071616 Kepler-16'],
				['star-system', 'primary', 'hip/2007/37279 0'],
				['star-system', 'simbad', '3396059'],
				['star-system', 'el-badry', '1+2'],
				['star-system', 'msc', '14396-6050 AB'],
				['star-system', 'wds', '14396-6050']
			])
		);
		expect(shown.map((r) => [r.label, r.value])).toEqual([
			['MSC', '14396-6050 AB'],
			['WDS', '14396-6050']
		]);
	});
});

describe('the class of a star system', () => {
	it('reads in words', () => {
		expect(starClassLabel('binary star')).toBe('Binary star');
		expect(starClassLabel('multiple star')).toBe('Multiple star');
	});
});
