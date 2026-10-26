import { describe, expect, it } from 'vitest';
import type { ExtrasolarCredit } from '$lib/fetch/extrasolar/files';
import { ExtrasolarLookup, type ExtrasolarRecord } from '$lib/fetch/extrasolar/lookup';
import {
	HAS_EXPORT,
	diskSource,
	exportMetadata,
	readExportJson
} from '$lib/fetch/extrasolar/__fixtures__/export';
import { pointSourceRecord, valueColumns } from '$lib/fetch/extrasolar/__fixtures__/record';
import type { PlanetSystem } from '$lib/fetch/extrasolar/planets';
import {
	CREDIT_PAGES,
	localizedStarCredit,
	planetCredits,
	starCredits,
	starSourceName
} from './star-sources';

describe('star sources', () => {
	it('names the sources the tables name', () => {
		expect(starSourceName('gaia-dr3')).toBe('Gaia DR3');
		expect(starSourceName('gaia-dr3-named')).toBe('Gaia DR3');
		expect(starSourceName('hipparcos-2007')).toBe('Hipparcos (2007)');
		expect(starSourceName('andrae-2023')).toBe('Gaia XP (Andrae et al. 2023)');
		expect(starSourceName('gaia-dr3-gspphot')).toBe('Gaia DR3 GSP-Phot');
		expect(starSourceName('gaia-dr3-nss')).toBe('Gaia DR3 orbit solution');
		expect(starSourceName('hipparcos-1997')).toBe('Hipparcos (1997)');
		expect(starSourceName('simbad')).toBe('SIMBAD');
		expect(starSourceName('simbad-hip')).toBe('SIMBAD');
		expect(starSourceName('reyle-2021')).toBe('Reylé et al. 2021');
		expect(starSourceName('ultracoolsheet')).toBe('UltracoolSheet');
		expect(starSourceName('hunt-reffert-2024')).toBe('Hunt & Reffert 2024');
		expect(starSourceName('magellanic-clouds')).toBe('Magellanic Clouds');
		expect(starSourceName('bailer-jones-2021')).toBe('Bailer-Jones et al. 2021');
		expect(starSourceName('literature')).toBe('Published paper');
		expect(starSourceName('nasa-exoplanet-archive')).toBe('NASA Exoplanet Archive');
		expect(starSourceName('exoplanet-eu')).toBe('exoplanet.eu');
		expect(starSourceName('open-exoplanet-catalogue')).toBe('Open Exoplanet Catalogue');
		expect(starSourceName('iau-nameexoworlds')).toBe('IAU NameExoWorlds');
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

describe('star credits', () => {
	// One credit per page, labelled with its page's key.
	const credits: ExtrasolarCredit[] = Object.entries(CREDIT_PAGES).map(([key, page]) => ({
		name: key,
		organisation: 'Test',
		source: `https://example.org${page}`
	}));
	const record = (
		values: Record<string, number | string>,
		nameSource: string | null
	): ExtrasolarRecord => {
		const star = pointSourceRecord(valueColumns(values), credits);
		return { ...star, metadata: { ...star.metadata, nameSource } };
	};
	const labels = (values: Record<string, number | string>, nameSource: string | null) =>
		starCredits(record(values, nameSource)).map((c) => c.label);
	const noParallax = { parallax: 0.01, parallax_error: 0.05 };
	const smith = { short: 'Smith 2006', title: 'The Homunculus', url: 'https://doi.org/x' };

	it('credits SIMBAD and the paper of the cloud', () => {
		const smc = { distance: 62_440, distance_source: 'magellanic-clouds' };
		expect(labels({ ...noParallax, ...smc, astrometry_source: 'simbad' }, 'simbad')).toEqual([
			'simbad',
			'smc'
		]);
		const lmc = { distance: 49_590, distance_source: 'magellanic-clouds' };
		const gaia = { astrometry_source: 'gaia-dr3-named', gaia_photometry_source: 'gaia-dr3-named' };
		expect(labels({ ...noParallax, ...lmc, ...gaia }, 'gaia-dr3-named')).toEqual(['gaia', 'lmc']);
	});

	it('credits each distance catalogue when the panel shows its distance', () => {
		const pages = {
			'simbad-parallax': 'simbad',
			'reyle-2021': 'reyle',
			ultracoolsheet: 'ultracoolsheet',
			'hunt-reffert-2024': 'huntReffert',
			'bailer-jones-2021': 'bailerJones'
		};
		for (const [source, page] of Object.entries(pages)) {
			const row = { ...noParallax, distance: 20, distance_source: source };
			expect(labels(row, null)).toEqual([page]);
		}
	});

	it('leaves out the distance catalogue where a 5σ parallax gives the distance', () => {
		const row = { parallax: 500, parallax_error: 0.1, distance: 2, distance_source: 'reyle-2021' };
		expect(labels({ ...row, astrometry_source: 'gaia-dr3' }, 'gaia-dr3')).toEqual(['gaia']);
	});

	it('credits the Hipparcos catalogue of 1997 for its entries', () => {
		const row = {
			astrometry_source: 'hipparcos-1997',
			hipparcos_photometry_source: 'hipparcos-1997'
		};
		expect(labels(row, 'hipparcos-1997')).toEqual(['hipparcosPhotometry']);
	});

	it('cites the papers of a distance from the literature table', () => {
		const row = { ...noParallax, distance: 2350, distance_source: 'literature' };
		const found = starCredits(record(row, null), { distance: [smith] });
		expect(found).toEqual([
			{ key: smith.url, label: smith.title, url: smith.url, note: 'Smith 2006' }
		]);
		// The entry has not loaded.
		expect(starCredits(record(row, null))).toEqual([]);
		// A paper's distance beats a 5σ parallax, so it is still cited.
		const parallax = { ...row, parallax: 500, parallax_error: 0.1 };
		expect(starCredits(record(parallax, null), { distance: [smith] })).toEqual(found);
	});

	it("names the credit of the literature table in the reader's language", () => {
		const literature = credits.find((c) => c.name === 'literature')!;
		expect(localizedStarCredit(literature)).toEqual({
			...literature,
			name: 'Published papers',
			organisation: "cited on each star's page"
		});
		const gaia = credits.find((c) => c.name === 'gaia')!;
		expect(localizedStarCredit(gaia)).toBe(gaia);
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
		// Sirius's [Fe/H] is from PASTEL, by its SIMBAD id, beside XHIP's.
		expect(await labels(22137869)).toEqual([
			'The PASTEL catalogue, 2020 version (B/pastel)',
			'SIMBAD astronomical database',
			'Hipparcos, the new reduction (I/311)',
			'The Hipparcos and Tycho Catalogues (I/239)',
			'Extended Hipparcos Compilation, XHIP (V/137D)',
			'IAU Catalog of Star Names'
		]);
		// The panel shows the values of Proxima's exoplanet catalogue.
		expect(await labels(27424668)).toEqual([
			'Gaia Data Release 3',
			'Astrometric fidelity of Gaia EDR3',
			'The PASTEL catalogue, 2020 version (B/pastel)',
			'SIMBAD astronomical database',
			'The Hipparcos and Tycho Catalogues (I/239)',
			'NASA Exoplanet Archive, Planetary Systems Composite Parameters',
			'IAU Catalog of Star Names'
		]);
		expect(await labels(7544072308)).toEqual([
			'Gaia Data Release 3',
			'Astrometric fidelity of Gaia EDR3'
		]);
	});
});

describe.skipIf(!HAS_EXPORT)('planet credits from the real export', () => {
	const credits = HAS_EXPORT ? exportMetadata().credits : [];

	it('finds a credit in the export for each exoplanet catalogue', () => {
		const sources = credits.map((c) => c.source);
		for (const page of [
			CREDIT_PAGES.nasaExoplanetArchive,
			CREDIT_PAGES.exoplanetEu,
			CREDIT_PAGES.openExoplanetCatalogue,
			CREDIT_PAGES.nameExoWorlds
		]) {
			expect(sources.filter((s) => s.includes(page))).toHaveLength(1);
		}
	});

	it('credits the catalogues behind a planet, and those behind its star', async () => {
		const alphaCen = readExportJson<PlanetSystem>('planets/27424668.json.gz');
		const proximaB = alphaCen.planets.find((p) => p.number === 1 && p.host === 27424668)!;
		expect(planetCredits(proximaB, credits).map((c) => c.label)).toEqual([
			'NASA Exoplanet Archive, Planetary Systems Composite Parameters',
			'Open Exoplanet Catalogue'
		]);
		const lookup = new ExtrasolarLookup(diskSource());
		const lich = await lookup.lookup('1634188199');
		if (lich.kind !== 'live') throw new Error('Lich not found');
		expect(starCredits(lich.record).map((c) => c.label)).toContain(
			'NASA Exoplanet Archive, Planetary Systems Composite Parameters'
		);
	});
});
