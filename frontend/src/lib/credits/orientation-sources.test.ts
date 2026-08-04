/**
 * The sidebar and the scene's attribution popover both credit a body's
 * rotational elements, and they must never disagree — this mapper is the one
 * place that decides who published a pole.
 */

import { describe, expect, it, vi } from 'vitest';

vi.mock('$lib/paraglide/messages.js', () => ({
	source_iau_wgccre_short: () => 'IAU WGCCRE',
	source_iau_wgccre_name: () => 'IAU Working Group on Cartographic Coordinates',
	source_iau_wgccre_role: () => 'rotation & radii',
	source_spice_pck_name: () => 'NASA SPICE PCK kernels (NAIF)',
	source_spice_pck_role: () => 'reference kernels',
	source_damit_name: () => 'DAMIT',
	source_spin_pole_role: () => 'spin pole & rotation period'
}));

import { orientationCredits } from './orientation-sources';

const MORGADO = {
	title: 'Morgado et al. 2021 (A&A 652, A141)',
	url: 'https://doi.org/10.1051/0004-6361/202141543'
};

describe('orientationCredits', () => {
	it('credits the IAU and NAIF for a PCK pole', () => {
		expect(orientationCredits('pck').map((c) => c.key)).toEqual(['iau-wgccre', 'naif']);
	});

	it('treats a pre-`source` bundle as PCK — all the table used to hold', () => {
		expect(orientationCredits(undefined)).toEqual(orientationCredits('pck'));
	});

	it('credits DAMIT, not the IAU, for a lightcurve pole', () => {
		const credits = orientationCredits('lightcurve');
		expect(credits.map((c) => c.key)).toEqual(['damit']);
		expect(credits[0].short).toBe('DAMIT');
	});

	it('credits the paper an occultation pole was fitted in', () => {
		const [credit] = orientationCredits('occultation', MORGADO);
		expect(credit.key).toBe(MORGADO.url);
		expect(credit.short).toBe(MORGADO.title);
	});

	it('credits nobody for an occultation pole with no reference', () => {
		// Better a missing row than the IAU credited for a paper's measurement.
		expect(orientationCredits('occultation')).toEqual([]);
	});

	it('gives both surfaces a label: compact for the sidebar, full for the popover', () => {
		const [iau] = orientationCredits('pck');
		expect(iau.short).toBe('IAU WGCCRE');
		expect(iau.long.length).toBeGreaterThan(iau.short.length);
	});
});
