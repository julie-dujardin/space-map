import { describe, expect, it } from 'vitest';
import { ExtrasolarLookup } from '$lib/fetch/extrasolar/lookup';
import { HAS_EXPORT, diskSource, exportMetadata } from '$lib/fetch/extrasolar/__fixtures__/export';
import { pointSourceRecord } from '$lib/fetch/extrasolar/__fixtures__/record';
import { CREDIT_PAGES, starCredits, starSourceName } from './star-sources';

describe('star sources', () => {
	it('names the sources the tables name', () => {
		expect(starSourceName('gaia-dr3')).toBe('Gaia DR3');
		expect(starSourceName('hipparcos-2007')).toBe('Hipparcos (2007)');
		expect(starSourceName('andrae-2023')).toBe('Gaia XP (Andrae et al. 2023)');
		expect(starSourceName('gaia-dr3-gspphot')).toBe('Gaia DR3 GSP-Phot');
		expect(starSourceName('gaia-dr3-nss')).toBe('Gaia DR3 orbit solution');
		expect(starSourceName('unknown')).toBe('unknown');
	});

	it('credits the XP metallicities where the record has them', () => {
		const credit = {
			name: 'Metallicities from Gaia XP spectra',
			organisation: 'Andrae, Rix & Chandra 2023',
			source: 'https://doi.org/10.5281/zenodo.7945154',
			license: 'CC BY 4.0'
		};
		const record = pointSourceRecord(
			[{ name: 'xgboost_source', type: 'dict', values: ['gaia-dr3'] }],
			[credit]
		);
		expect(starCredits(record)).toEqual([
			{
				key: credit.source,
				label: credit.name,
				url: credit.source,
				note: 'Andrae, Rix & Chandra 2023 · CC BY 4.0'
			}
		]);
		const without = pointSourceRecord(
			[{ name: 'xgboost_source', type: 'dict', values: [null] }],
			[credit]
		);
		expect(starCredits(without)).toEqual([]);
	});

	it('credits Gaia and the orbit paper where the record has an orbit', () => {
		const gaia = {
			name: 'Gaia Data Release 3',
			organisation: 'ESA/Gaia/DPAC',
			source: 'https://www.cosmos.esa.int/web/gaia/dr3'
		};
		const orbits = {
			name: 'Gaia DR3 binary orbits and masses',
			organisation: 'Gaia Collaboration, Arenou et al. 2023',
			source: 'https://ui.adsabs.harvard.edu/abs/2023A&A...674A..34G'
		};
		const record = pointSourceRecord(
			[{ name: 'parallax', type: 'float32', values: [10] }],
			[gaia, orbits],
			[{ name: 'orbit_source', type: 'dict', values: ['gaia-dr3'] }]
		);
		expect(starCredits(record).map((c) => c.label)).toEqual([gaia.name, orbits.name]);
	});

	it('credits the catalogues of the joined rows and their ids', () => {
		const credits = [
			{
				name: 'PASTEL',
				organisation: 'a',
				source: 'https://cdsarc.cds.unistra.fr/viz-bin/cat/B/pastel'
			},
			{ name: 'SIMBAD', organisation: 'b', source: 'https://simbad.cds.unistra.fr/simbad/' },
			{
				name: 'LAMOST M dwarfs',
				organisation: 'c',
				source: 'https://doi.org/10.5281/zenodo.14030249'
			},
			{ name: 'LAMOST M stars', organisation: 'd', source: 'https://www.lamost.org/dr10/v2.0/' },
			{ name: 'APOGEE DR17', organisation: 'e', source: 'https://www.sdss4.org/dr17/irspec/' }
		];
		const labels = (column: string) =>
			starCredits(
				pointSourceRecord([{ name: column, type: 'dict', values: ['gaia-dr3'] }], credits)
			).map((c) => c.label);
		expect(labels('pastel_source')).toEqual(['PASTEL', 'SIMBAD']);
		expect(labels('lamost_source')).toEqual(['LAMOST M dwarfs', 'LAMOST M stars']);
		expect(labels('apogee_source')).toEqual(['APOGEE DR17']);
	});
});

describe.skipIf(!HAS_EXPORT)('star credits from the real export', () => {
	const lookup = new ExtrasolarLookup(diskSource());
	const labels = async (id: number) => {
		const result = await lookup.lookup(id);
		if (result.kind !== 'live') throw new Error(`${id} not found`);
		return starCredits(result.record).map((c) => c.label);
	};

	it('finds a credit in the export for each catalogue', () => {
		const sources = exportMetadata().credits.map((c) => c.source);
		for (const page of Object.values(CREDIT_PAGES)) {
			expect(sources.filter((s) => s.includes(page))).toHaveLength(1);
		}
	});

	it('credits the catalogues behind each star', async () => {
		expect(await labels(22137869)).toEqual([
			'Hipparcos, the new reduction (I/311)',
			'The Hipparcos and Tycho Catalogues (I/239)',
			'IAU Catalog of Star Names'
		]);
		expect(await labels(27424668)).toEqual([
			'Gaia Data Release 3',
			'Astrometric fidelity of Gaia EDR3',
			'The Hipparcos and Tycho Catalogues (I/239)',
			'IAU Catalog of Star Names'
		]);
		expect(await labels(7544072308)).toEqual([
			'Gaia Data Release 3',
			'Astrometric fidelity of Gaia EDR3'
		]);
	});
});
