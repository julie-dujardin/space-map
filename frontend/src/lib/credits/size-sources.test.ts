/** A size from a catalogue is credited to that catalogue. */

import { describe, expect, it } from 'vitest';

import { catalogueCredit, catalogueSizeCredit } from './size-sources';

describe('catalogueCredit', () => {
	it('credits a catalogue for the value the note names', () => {
		expect(catalogueCredit('sbdb', 'mass')).toEqual({
			key: 'sbdb',
			label: 'NASA JPL Small-Body Database',
			url: 'https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html',
			note: 'mass'
		});
	});

	it("links only Johnston's own entry for the body", () => {
		const page = 'https://www.johnstonsarchive.net/astro/astmoons/am-136199.html';
		expect(catalogueCredit('johnston', 'mass', page).url).toBe(page);
		expect(catalogueCredit('ssodnet', 'mass', page).url).toBe(
			'https://ssp.imcce.fr/webservices/ssodnet/'
		);
	});
});

describe('catalogueSizeCredit', () => {
	it("links Johnston's entry for the body where the bundle has one", () => {
		const page = 'https://www.johnstonsarchive.net/astro/astmoons/am-136199.html';
		expect(catalogueSizeCredit('johnston', page)).toMatchObject({ key: 'johnston', url: page });
	});

	it('credits an AsterSat size to the NSDB, for the size', () => {
		expect(catalogueSizeCredit('astersat')).toMatchObject({
			key: 'nsdb',
			url: 'https://www.sai.msu.ru/neb/nss/'
		});
	});

	it('credits an SsODNet size to SsODNet', () => {
		expect(catalogueSizeCredit('ssodnet')).toMatchObject({
			key: 'ssodnet',
			url: 'https://ssp.imcce.fr/webservices/ssodnet/',
			note: 'size & shape'
		});
	});

	it('leaves the PCK, papers and Wikidata to their own credits', () => {
		for (const source of ['pck', 'literature', 'occultation', 'photometry', 'wikidata'])
			expect(catalogueSizeCredit(source)).toBeNull();
	});
});
