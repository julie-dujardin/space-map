import { afterEach, describe, expect, it } from 'vitest';
import {
	inSceneCredits,
	isInteriorCredit,
	type ExtrasolarCredit,
	type ExtrasolarMetadata
} from '$lib/fetch/extrasolar/files';
import { configureHost } from '$lib/host';
import type { StarInterior } from '$lib/fetch/extrasolar/interior';
import {
	ExtrasolarLookup,
	type ExtrasolarRecord,
	type StarRadiusSource
} from '$lib/fetch/extrasolar/lookup';
import {
	HAS_EXPORT,
	diskSource,
	exportMetadata,
	readExportJson,
	systemKeyOf
} from '$lib/fetch/extrasolar/__fixtures__/export';
import { pointSourceRecord, valueColumns } from '$lib/fetch/extrasolar/__fixtures__/record';
import type { PlanetSystem } from '$lib/fetch/extrasolar/planets';
import {
	heldValues,
	member,
	pairOrbit,
	systemNodeOf
} from '$lib/fetch/extrasolar/__fixtures__/system-node';
import {
	CREDIT_PAGES,
	citationCredits,
	localizedStarCredit,
	planetCredits,
	shownStarCredits,
	starCredits,
	starInteriorCredits,
	starSourceName
} from './star-sources';
import { referenceCount } from './star-sources';

describe('star sources', () => {
	it('names the sources the tables name', () => {
		expect(starSourceName('gaia-dr3')).toBe('Gaia DR3');
		expect(starSourceName('gaia-dr3-named')).toBe('Gaia DR3');
		expect(starSourceName('hipparcos-2007')).toBe('Hipparcos (2007)');
		expect(starSourceName('andrae-2023')).toBe('Gaia XP (Andrae et al. 2023)');
		expect(starSourceName('gaia-dr3-gspphot')).toBe('Gaia DR3 GSP-Phot');
		expect(starSourceName('gaia-dr3-flame')).toBe('Gaia DR3 FLAME');
		expect(starSourceName('gaia-dr3-flame-spec')).toBe('Gaia DR3 FLAME (GSP-Spec)');
		expect(starSourceName('jmdc')).toBe('JMDC');
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
		expect(starSourceName('gcvs-5.1')).toBe('GCVS 5.1 (Samus et al. 2017)');
		expect(starSourceName('spicy')).toBe('SPICY (Kuhn et al. 2021)');
		expect(starSourceName('atnf-psrcat')).toBe('ATNF Pulsar Catalogue (Manchester et al. 2005)');
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
			{ name: 'APOGEE DR17', organisation: 'e', source: 'https://www.sdss4.org/dr17/irspec/' },
			{ name: 'GCVS 5.1', organisation: 'f', source: 'http://www.sai.msu.su/gcvs/gcvs/' },
			{ name: 'SPICY', organisation: 'g', source: 'https://doi.org/10.26131/IRSA556' },
			{
				name: 'ATNF Pulsar Catalogue',
				organisation: 'h',
				source: 'https://www.atnf.csiro.au/research/pulsar/psrcat'
			}
		];
		const labels = (column: string) =>
			starCredits(
				pointSourceRecord([{ name: column, type: 'dict', values: ['gaia-dr3'] }], credits)
			).map((c) => c.label);
		expect(labels('pastel_source')).toEqual(['PASTEL', 'SIMBAD']);
		expect(labels('lamost_source')).toEqual(['LAMOST M dwarfs', 'LAMOST M stars']);
		expect(labels('apogee_source')).toEqual(['APOGEE DR17']);
		expect(labels('gcvs_source')).toEqual(['SIMBAD', 'GCVS 5.1']);
		expect(labels('spicy_source')).toEqual(['SPICY']);
		expect(labels('atnf_source')).toEqual(['SIMBAD', 'ATNF Pulsar Catalogue']);
	});
});

describe('star credits', () => {
	// One credit per page, labelled with its page's key.
	const credits: ExtrasolarCredit[] = Object.entries(CREDIT_PAGES).map(([key, page]) => ({
		name: key,
		organisation: 'Test',
		source: `https://example.org${page}`
	}));
	const paper = { short: 'Smith 2020', title: 'Radii', url: 'https://example.org/paper' };
	const sized = (
		source: StarRadiusSource,
		columns = valueColumns({ angular_diameter_source: 'jmdc' })
	) => pointSourceRecord(columns, credits, undefined, { solar: 1, source });
	const radiusLabels = (source: StarRadiusSource) =>
		starCredits(sized(source), { paper_radius: [paper] }).map((c) => c.label);

	it('credits the source of the radius that the export picked', () => {
		expect(radiusLabels('jmdc')).toEqual(['jmdc']);
		expect(radiusLabels('gaia-dr3-flame')).toEqual(['gaia']);
		expect(radiusLabels('gaia-dr3-flame-spec')).toEqual(['gaia']);
		expect(radiusLabels('gaia-dr3-gspphot')).toEqual(['gaia']);
		expect(radiusLabels('nasa-exoplanet-archive')).toEqual(['nasaExoplanetArchive']);
		expect(radiusLabels('exoplanet-eu')).toEqual(['exoplanetEu']);
		expect(radiusLabels('open-exoplanet-catalogue')).toEqual(['openExoplanetCatalogue']);
		expect(radiusLabels('literature')).toEqual(['Radii']);
	});

	it('cites the paper of the point that gives a held star its radius', () => {
		const point = systemNodeOf(1, { point: true, paperRadius: true, radiusPapers: [paper] });
		const star = sized('literature', []);
		expect(starCredits(star, undefined, [], point).map((c) => c.label)).toEqual(['Radii']);
	});
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

	it('credits the catalogue of each value of a planet host', () => {
		const host = {
			...noParallax,
			host_star_source: 'nasa-exoplanet-archive',
			host_teff_source: 'exoplanet-eu',
			host_mass_source: 'open-exoplanet-catalogue',
			host_metallicity_source: 'nasa-exoplanet-archive',
			host_logg_source: 'nasa-exoplanet-archive',
			host_age_source: 'nasa-exoplanet-archive'
		};
		expect(labels(host, null)).toEqual([
			'nasaExoplanetArchive',
			'exoplanetEu',
			'openExoplanetCatalogue'
		]);
		expect(labels({ ...noParallax, host_teff_source: 'exoplanet-eu' }, null)).toEqual([
			'exoplanetEu'
		]);
	});

	it("credits only the name and distance catalogue of a point's host values, which it does not show", () => {
		const star = record(
			{
				...noParallax,
				host_star_source: 'nasa-exoplanet-archive',
				host_teff_source: 'exoplanet-eu'
			},
			null
		);
		const node = {
			...star,
			rows: new Map([...star.rows, ['system', star.rows.get('point-source')!]])
		};
		expect(starCredits(node).map((c) => c.label)).toEqual(['nasaExoplanetArchive']);
	});

	it('credits the planet catalogue of each value of a held star', () => {
		const held = systemNodeOf(1, {
			star: heldValues({
				massSource: 'nasa-exoplanet-archive',
				teffSource: 'exoplanet-eu',
				spectralTypeSource: 'literature'
			})
		});
		const star = sized('literature', []);
		expect(starCredits(star, undefined, [held]).map((c) => c.label)).toEqual([
			'nasaExoplanetArchive',
			'exoplanetEu'
		]);
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
		const meta = exportMetadata();
		const sources = meta.credits.map((c) => c.source);
		// The export lists a work of the fitted interiors only where a row used it.
		const interior: string[] = [
			CREDIT_PAGES.mist,
			CREDIT_PAGES.casagrande,
			CREDIT_PAGES.flower,
			CREDIT_PAGES.torres
		];
		for (const page of Object.values(CREDIT_PAGES)) {
			const found = sources.filter((s) => s.includes(page));
			if (interior.includes(page)) {
				expect(found.length).toBeLessThanOrEqual(meta.tables.interior ? 1 : 0);
				continue;
			}
			// ORB6's page is under the WDS's.
			expect(found).toHaveLength(page === CREDIT_PAGES.wds ? 2 : 1);
		}
		const works = interior.filter((page) => sources.some((s) => s.includes(page)));
		// The relations come with the models.
		if (works.length) expect(works[0]).toBe(CREDIT_PAGES.mist);
	});

	it('credits the catalogues behind each star', async () => {
		// Sirius's [Fe/H] is from PASTEL, by its SIMBAD id, beside XHIP's.
		expect(await labels(22137869)).toEqual([
			'The PASTEL catalogue, 2020 version (B/pastel)',
			'JMDC: JMMC Measured Stellar Diameters Catalogue (II/345)',
			'SIMBAD astronomical database',
			'Hipparcos, the new reduction (I/311)',
			'The Hipparcos and Tycho Catalogues (I/239)',
			'Extended Hipparcos Compilation, XHIP (V/137D)',
			'IAU Catalog of Star Names'
		]);
		// The panel shows Proxima's GCVS name (V645 Cen) and the values of its
		// exoplanet catalogue.
		expect(await labels(27424668)).toEqual([
			'Gaia Data Release 3',
			'Astrometric fidelity of Gaia EDR3',
			'The PASTEL catalogue, 2020 version (B/pastel)',
			'SIMBAD astronomical database',
			'General Catalogue of Variable Stars, GCVS 5.1',
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
		const alphaCen = readExportJson<PlanetSystem>(`planets/${systemKeyOf(27424668)}.json.gz`);
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

describe('the credits of a star system', () => {
	const credits: ExtrasolarCredit[] = [
		['WDS', 'https://www.astro.gsu.edu/wds/'],
		['MSC', 'http://www.ctio.noirlab.edu/~atokovin/stars/'],
		['ORB6', 'https://www.astro.gsu.edu/wds/orb6.html'],
		['SBX', 'https://astro.ulb.ac.be/sbx/'],
		['El-Badry', 'https://doi.org/10.5281/zenodo.4435257'],
		['Metallicity', 'https://doi.org/10.5281/zenodo.7945154']
	].map(([name, source]) => ({ name, source, organisation: '', license: null }) as never);
	const record = (columns: Record<string, string>, node = false) => {
		const star = pointSourceRecord(valueColumns(columns), credits);
		return node
			? { ...star, rows: new Map([...star.rows, ['system', star.rows.get('point-source')!]]) }
			: star;
	};

	it('credits the trees and the sources of the elements a panel shows', () => {
		const node = systemNodeOf(1, {
			sources: ['wds', 'el-badry-2021'],
			members: [member(2, { source: 'msc' })],
			orbit: pairOrbit({ periodSource: 'orb6', semiMajorAxisSource: 'sbx' })
		});
		const labels = starCredits(record({}), undefined, [node]).map((c) => c.label);
		expect(labels).toEqual(expect.arrayContaining(['WDS', 'MSC', 'ORB6', 'SBX', 'El-Badry']));
		expect(starCredits(record({}), undefined, [systemNodeOf(1, { sources: ['wds'] })])).toEqual([
			expect.objectContaining({ label: 'WDS' })
		]);
	});

	it('leaves out a metallicity on a node, which shows none', () => {
		const columns = { xgboost_source: 'andrae-2023' };
		expect(starCredits(record(columns)).map((c) => c.label)).toEqual(['Metallicity']);
		expect(starCredits(record(columns, true))).toEqual([]);
	});

	it('cites a work by its title, else by its key, linked when it has a link', () => {
		const out = citationCredits([
			{
				source: 'msc',
				reference: 'x',
				short: 'Doyle et al. 2011',
				title: 'Title',
				url: 'https://a'
			},
			{ source: 'orb6', reference: 'Krv2017', short: null, title: null, url: null },
			{ source: 'sbx', reference: 'y', short: null, title: null, url: 'https://a' }
		]);
		expect(out).toEqual([
			{ key: 'https://a', label: 'Title', url: 'https://a', note: 'Doyle et al. 2011' },
			{ key: 'Krv2017', label: 'Krv2017', url: undefined, note: undefined }
		]);
	});

	it('names a work by a later citation with a title, in the place of the first', () => {
		const out = citationCredits([
			{ source: 'sbx', reference: 'y', short: null, title: null, url: 'https://a' },
			{ source: 'orb6', reference: 'Krv2017', short: null, title: null, url: null },
			{ source: 'msc', reference: 'x', short: 'One', title: 'Title', url: 'https://a' },
			{ source: 'msc', reference: 'z', short: 'Two', title: 'Other', url: 'https://a' }
		]);
		expect(out.map((work) => work.label)).toEqual(['Title', 'Krv2017']);
		expect(out[0].note).toBe('One');
	});
});

describe('inSceneCredits', () => {
	const source = 'https://example.org/';

	it('keeps the catalogues, and leaves papers and Wikidata to /credits', () => {
		const credits: ExtrasolarCredit[] = [
			{ name: 'Gaia Data Release 3', organisation: 'ESA/Gaia/DPAC', source },
			{ name: 'Geometric distances', organisation: 'Bailer-Jones et al. 2021', source },
			{ name: 'Wide binaries', organisation: 'El-Badry, Rix & Heintz 2021', source },
			{
				name: 'Published papers',
				organisation: 'Cited on each page',
				source: `${source}constants/stars/literature.py`
			},
			{
				name: 'Wikidata',
				organisation: 'Wikidata contributors',
				source: 'https://www.wikidata.org/'
			}
		];
		expect(credits.filter(inSceneCredits).map((c) => c.name)).toEqual(['Gaia Data Release 3']);
	});
});

describe('referenceCount', () => {
	const credit = (organisation: string, source: string, citation?: string) => ({
		name: organisation,
		organisation,
		source,
		citation
	});
	const row = (url: string) => ({ title: url, url, contribution: 'x' });

	it('counts a work of two sections once, and the papers of the catalogues', () => {
		const credits = {
			systems: [],
			ephemeris_archives: [],
			ring_references: [row('https://doi.org/a')],
			star_references: [row('https://doi.org/a'), row('https://doi.org/b')]
		};
		const stars = [
			credit('Tokovinin 2018', 'https://doi.org/b', 'Tokovinin 2018, cited'),
			credit('Hunt & Reffert 2024', 'https://doi.org/c', 'Hunt & Reffert 2024, cited'),
			credit('ESA', 'https://example.org/catalogue', 'ESA 1997')
		];
		expect(referenceCount(credits, stars)).toBe(3);
	});
});

describe('the credits of a star interior', () => {
	// As the export writes them: the models, then the works of the colour routes.
	const credits: ExtrasolarCredit[] = [
		{
			name: 'Gaia Data Release 3',
			organisation: 'ESA/Gaia/DPAC',
			source: 'https://www.cosmos.esa.int/web/gaia/dr3'
		},
		{
			name: 'JMDC',
			organisation: 'Chelli et al. 2016',
			source: 'https://cdsarc.cds.unistra.fr/viz-bin/cat/II/345'
		},
		{
			name: 'SIMBAD',
			organisation: 'CDS',
			source: 'https://simbad.cds.unistra.fr/'
		},
		{
			name: 'Hipparcos 2007',
			organisation: 'van Leeuwen 2007',
			source: 'https://cdsarc.cds.unistra.fr/viz-bin/cat/I/311'
		},
		{
			name: 'Hipparcos 1997',
			organisation: 'ESA 1997',
			source: 'https://cdsarc.cds.unistra.fr/viz-bin/cat/I/239'
		},
		{
			name: 'NASA Exoplanet Archive',
			organisation: 'NExScI',
			source: 'https://exoplanetarchive.ipac.caltech.edu/'
		},
		{
			name: 'MIST v2.5 stellar evolution tracks',
			organisation: 'MESA Isochrones and Stellar Tracks',
			source: 'https://mist.science/',
			citation: 'Dotter et al. 2026, ApJS 283, 64; Choi et al. 2016, ApJ 823, 102'
		},
		{
			name: 'Teff scale',
			organisation: 'Casagrande et al. 2010',
			source: 'https://doi.org/10.1051/0004-6361/200913204'
		},
		{
			name: 'Transformations',
			organisation: 'Flower 1996',
			source: 'https://doi.org/10.1086/177785'
		},
		{
			name: 'Bolometric corrections',
			organisation: 'Torres 2010',
			source: 'https://doi.org/10.1088/0004-6256/140/5/1158'
		}
	];
	const fit = (over: Partial<StarInterior>): StarInterior => ({
		id: 1,
		tier: 2,
		curated: null,
		stage: 'main_sequence',
		feh: 0,
		fehSource: 'assumed-solar',
		teff: 5800,
		teffSource: 'gaia-dr3-gspphot',
		luminositySource: 'gaia-dr3-flame',
		mass: { value: 1, range: null },
		radius: { value: 1, range: null },
		envelopeBaseRadius: { value: 0.7, range: null },
		envelopeBaseMass: { value: 0.98, range: null },
		convectiveCoreMass: null,
		heliumCoreMass: null,
		centreTemperature: { value: null, range: null },
		centreDensity: { value: null, range: null },
		centreX: null,
		centreY: null,
		...over
	});

	// A Hipparcos star at 10 pc, with no Gaia values.
	const HIPPARCOS = {
		parallax: 100,
		parallax_error: 0.5,
		astrometry_source: 'hipparcos-2007',
		hipparcos_photometry_source: 'hipparcos-2007',
		v_mag: 4.4,
		b_v: 0.65
	};
	const star = (values: Record<string, number | string> = {}) =>
		pointSourceRecord(valueColumns(values), credits);
	const paper = { short: 'Boyajian et al. 2012', title: 'Radii', url: 'https://doi.org/10.1/r' };
	const labels = (
		over: Partial<StarInterior>,
		values: Record<string, number | string> = HIPPARCOS,
		references = {}
	) => starInteriorCredits(fit(over), star(values), references).map((c) => c.label);

	it('credits the models first, then the catalogues of the inputs', () => {
		expect(labels({}, {})).toEqual(['MIST v2.5 stellar evolution tracks', 'Gaia Data Release 3']);
	});

	it('credits the relations and the photometry that a Teff from B − V came from', () => {
		expect(labels({ teffSource: 'casagrande-2010' })).toEqual([
			'MIST v2.5 stellar evolution tracks',
			'Gaia Data Release 3',
			'Hipparcos 1997',
			'Teff scale'
		]);
		const simbad = { ...HIPPARCOS, b_v: Number.NaN, simbad_b_mag: 5, simbad_v_mag: 4.4 };
		expect(labels({ teffSource: 'flower-1996' }, simbad)).toContain('SIMBAD');
	});

	it('credits the V and the distance of a luminosity from a bolometric correction', () => {
		expect(
			labels({ teffSource: 'flower-1996', luminositySource: 'bolometric-correction' })
		).toEqual([
			'MIST v2.5 stellar evolution tracks',
			'Hipparcos 2007',
			'Hipparcos 1997',
			'Transformations',
			'Bolometric corrections'
		]);
	});

	it('credits the source of the radius that a luminosity came from', () => {
		const radius = { teffSource: 'host-star', luminositySource: 'radius' };
		const host = {
			...HIPPARCOS,
			host_star_source: 'exoplanet-eu',
			host_teff_source: 'nasa-exoplanet-archive'
		};
		expect(labels(radius, { ...host, radius_literature: 1.1 }, { paper_radius: [paper] })).toEqual([
			'MIST v2.5 stellar evolution tracks',
			'NASA Exoplanet Archive',
			'Radii'
		]);
		expect(labels(radius, { ...host, angular_diameter: 1.5 })).toEqual([
			'MIST v2.5 stellar evolution tracks',
			'JMDC',
			'Hipparcos 2007',
			'NASA Exoplanet Archive'
		]);
	});

	it('cites the papers of a curated interior, from its block', () => {
		const curated = {
			structure: 'fluid',
			layers: [],
			sources: [{ title: 'Paper 2002 (A&A 1)', url: 'https://doi.org/10.1/x', note: 'layers' }]
		};
		expect(starInteriorCredits(fit({ tier: 0, curated }), star())).toEqual([
			{
				key: 'https://doi.org/10.1/x',
				label: 'Paper 2002 (A&A 1)',
				url: 'https://doi.org/10.1/x',
				note: 'layers'
			}
		]);
	});

	it('keeps the models out of the scene credits, which draw no interior', () => {
		expect(credits.filter(inSceneCredits).map((c) => c.name)).toEqual([
			'Gaia Data Release 3',
			'SIMBAD',
			'NASA Exoplanet Archive'
		]);
		expect(credits.filter(isInteriorCredit).map((c) => c.name)).toEqual([
			'MIST v2.5 stellar evolution tracks'
		]);
	});

	it('names the inputs of a fit', () => {
		expect(starSourceName('gaia-dr3-flame')).toBe('Gaia DR3 FLAME');
		expect(starSourceName('flower-1996')).toBe('B − V, Flower 1996');
		expect(starSourceName('radius')).toBe('Measured radius');
		expect(starSourceName('host-star')).toBe('Planet catalogues');
	});
});

describe('the star credits that /credits lists', () => {
	afterEach(() => configureHost({}));
	const credit = (name: string, source: string) =>
		({ name, source, organisation: 'X', license: null }) as never as ExtrasolarCredit;
	const meta = {
		tables: {
			'point-source': { distribution: 'non-commercial' },
			interior: { distribution: 'site-only' }
		},
		credits: [
			credit('Gaia', 'https://www.cosmos.esa.int/web/gaia/dr3'),
			credit('MIST', 'https://mist.science/'),
			credit('Flower', 'https://doi.org/10.1086/177785')
		]
	} as never as ExtrasolarMetadata;

	it('lists the works of the Interior table only where the host may show it', () => {
		configureHost({ textures: 'non-commercial' });
		expect(shownStarCredits(meta).map((c) => c.name)).toEqual(['Gaia']);
		configureHost({ textures: 'site-only' });
		expect(shownStarCredits(meta).map((c) => c.name)).toEqual(['Gaia', 'MIST', 'Flower']);
		configureHost({ textures: 'open' });
		expect(shownStarCredits(meta)).toEqual([]);
	});
});
