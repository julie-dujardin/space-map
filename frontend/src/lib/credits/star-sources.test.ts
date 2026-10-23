import { describe, expect, it } from 'vitest';
import { ExtrasolarLookup } from '$lib/fetch/extrasolar/lookup';
import { HAS_EXPORT, diskSource, exportMetadata } from '$lib/fetch/extrasolar/__fixtures__/export';
import { CREDIT_PAGES, starCredits, starSourceName } from './star-sources';

describe('star sources', () => {
	it('names the sources the tables name', () => {
		expect(starSourceName('gaia-dr3')).toBe('Gaia DR3');
		expect(starSourceName('hipparcos-2007')).toBe('Hipparcos (2007)');
		expect(starSourceName('unknown')).toBe('unknown');
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
