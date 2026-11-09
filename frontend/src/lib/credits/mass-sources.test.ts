/** A body's mass is credited to the source the export took it from. */

import { describe, expect, it } from 'vitest';
import type { BodyMassFields, BodyMassSource } from '$lib/fetch/objects/object-data';
import { massCredit, massCredits } from './mass-sources';

const mass = (source: BodyMassSource, fields: BodyMassFields = {}): BodyMassFields => ({
	mass_kg: 1e20,
	mass_source: source,
	...fields
});

describe('massCredit', () => {
	it('credits the kernels and each catalogue by the key the panel credits them under', () => {
		const sources: BodyMassSource[] = [
			'jpl_satellite_physical',
			'pck',
			'sbdb',
			'ssodnet',
			'astersat',
			'johnston',
			'wikidata'
		];
		expect(sources.map((source) => [source, massCredit(mass(source))?.key])).toEqual([
			['jpl_satellite_physical', 'jpl-satellite-physical'],
			['pck', 'naif'],
			['sbdb', 'sbdb'],
			['ssodnet', 'ssodnet'],
			['astersat', 'nsdb'],
			['johnston', 'johnston'],
			['wikidata', 'wikidata']
		]);
	});

	it("links JPL's satellite table and SsODNet", () => {
		expect(massCredit(mass('jpl_satellite_physical'))).toMatchObject({
			label: 'JPL Planetary Satellite Physical Parameters',
			url: 'https://ssd.jpl.nasa.gov/sats/phys_par/',
			note: 'mass'
		});
		expect(massCredit(mass('ssodnet'))).toMatchObject({
			label: 'SsODNet',
			url: 'https://ssp.imcce.fr/webservices/ssodnet/'
		});
	});

	it('names the ephemeris or the kernel the mass was read from', () => {
		const credit = massCredit(mass('jpl_satellite_physical', { mass_reference: 'PLU060' }));
		expect(credit?.note).toBe('mass, PLU060');
	});

	it("links the body's own Johnston entry where the bundle has one", () => {
		const page = 'https://www.johnstonsarchive.net/astro/astmoons/am-00022.html';
		expect(massCredit(mass('johnston'), page)?.url).toBe(page);
		expect(massCredit(mass('sbdb'), page)?.url).toBe(
			'https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html'
		);
	});

	it('credits nothing without a mass', () => {
		expect(massCredit({})).toBeNull();
		expect(massCredit({ mass_source: 'pck' })).toBeNull();
	});

	it('credits the paper of a mass from the literature, not NAIF', () => {
		const paper = {
			title: 'Pätzold et al. 2011 (Science 334, 491)',
			url: 'https://doi.org/10.1126/science.1209389'
		};
		expect(massCredit(mass('literature', { mass_reference: paper }))).toEqual({
			key: paper.url,
			label: paper.title,
			url: paper.url,
			note: 'mass',
			paper: true
		});
	});

	it('credits no one for an estimate the export made', () => {
		expect(massCredit(mass('estimate', { mass_nominal: true }))).toBeNull();
	});
});

describe('massCredits', () => {
	it('credits each catalogue once', () => {
		const planets = [
			mass('pck', { mass_reference: 'gm_de440.tpc' }),
			mass('pck', { mass_reference: 'gm_de440.tpc' }),
			mass('wikidata'),
			{}
		];
		expect(massCredits(planets).map((credit) => credit.key)).toEqual(['naif', 'wikidata']);
	});
});
