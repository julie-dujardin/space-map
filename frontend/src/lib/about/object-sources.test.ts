/** Each source key of the about page's objects resolves to a named link. */

import { describe, expect, it } from 'vitest';
import { sourceLinks } from './object-sources';

describe('sourceLinks', () => {
	it('links the mass and size sources that `entry_sources` counts', () => {
		const keys = [
			'pck',
			'jpl-satellite-physical',
			'sbdb',
			'ssodnet',
			'nsdb',
			'johnston',
			'wikidata'
		];
		for (const key of keys) {
			const links = sourceLinks(key);
			expect(links.length, key).toBeGreaterThan(0);
			for (const link of links) expect(link.url, key).toMatch(/^https:\/\//);
		}
	});

	it("names JPL's satellite table and SsODNet", () => {
		expect(sourceLinks('jpl-satellite-physical')).toEqual([
			{
				label: 'JPL Planetary Satellite Physical Parameters',
				url: 'https://ssd.jpl.nasa.gov/sats/phys_par/'
			}
		]);
		expect(sourceLinks('ssodnet')).toEqual([
			{ label: 'SsODNet', url: 'https://ssp.imcce.fr/webservices/ssodnet/' }
		]);
	});
});
