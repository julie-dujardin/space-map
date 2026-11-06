/** A size from an asteroid-moon catalogue is credited to that catalogue. */

import { describe, expect, it } from 'vitest';

import { catalogueSizeCredit } from './size-sources';

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

	it('leaves the PCK, papers and Wikidata to their own credits', () => {
		for (const source of ['pck', 'occultation', 'photometry', 'wikidata'])
			expect(catalogueSizeCredit(source)).toBeNull();
	});
});
