import { describe, expect, it } from 'vitest';
import { ExtrasolarLookup, type ExtrasolarRecord } from '$lib/fetch/extrasolar/lookup';
import { HAS_EXPORT, diskSource } from '$lib/fetch/extrasolar/__fixtures__/export';
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
