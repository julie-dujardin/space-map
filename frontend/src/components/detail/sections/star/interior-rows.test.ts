/**
 * The rows above a star's cross-section: the model line by tier, and the
 * centre given as ranges, never as a bare value.
 */

import { describe, expect, it } from 'vitest';
import type { Fitted, StarInterior } from '$lib/fetch/extrasolar/interior';
import { starInteriorBlock } from '$lib/charts/star-interior';
import { layerName } from '$lib/charts/interior-layers';
import { modelRow, starInteriorRows } from './interior-rows';

const NONE: Fitted = { value: null, range: null };

function fitted(over: Partial<StarInterior>): StarInterior {
	return {
		id: 1,
		tier: 1,
		curated: null,
		stage: 'main_sequence',
		feh: 0,
		fehSource: 'pastel-2020',
		teffSource: 'gaia-dr3-gspphot',
		luminositySource: 'gaia-dr3-flame',
		mass: { value: 1, range: [0.9, 1.1] },
		radius: { value: 1, range: [0.95, 1.05] },
		envelopeBaseRadius: { value: 0.7, range: [0.65, 0.75] },
		envelopeBaseMass: { value: 0.975, range: [0.97, 0.98] },
		convectiveCoreMass: [0, 0],
		heliumCoreMass: [0, 0],
		centreTemperature: { value: 1.6e7, range: [1.5e7, 1.7e7] },
		centreDensity: { value: 150, range: [100, 200] },
		centreX: [0.3, 0.5],
		centreY: [0.5, 0.7],
		...over
	};
}

function rowsOf(interior: StarInterior) {
	return starInteriorRows(interior, starInteriorBlock(interior, 1e6)!);
}

describe('the model row', () => {
	it('names the paper of a curated interior, with its link', () => {
		const curated = {
			structure: 'fluid',
			layers: [{ role: 'convective_zone', outer_radius_km: 1, composition: [] }],
			sources: [{ title: 'Paper 2002 (A&A 1)', url: 'https://doi.org/10.1/x' }]
		};
		const interior = fitted({ tier: 0, curated, mass: NONE, envelopeBaseRadius: NONE });
		expect(modelRow(interior, curated)).toEqual({
			label: 'Model',
			value: 'Paper 2002 (A&A 1)',
			href: 'https://doi.org/10.1/x'
		});
	});

	it('says what a fit rests on, by tier', () => {
		const note = (over: Partial<StarInterior>) => rowsOf(fitted(over))[0].note;
		expect(rowsOf(fitted({}))[0].value).toBe('Fit to stellar models');
		expect(note({ tier: 1 })).toBe('measured inputs');
		expect(note({ tier: 2 })).toBe('photometric inputs');
		expect(note({ tier: 3, fehSource: 'assumed-solar' })).toBe('solar metallicity assumed');
		expect(note({ tier: 3, fehSource: 'pastel-2020' })).toBe('uncertain inputs');
	});

	it('names the inputs of the fit on the value', () => {
		expect(rowsOf(fitted({}))[0].tooltip).toBe(
			'Effective temperature: Gaia DR3 GSP-Phot. Luminosity: Gaia DR3 FLAME. Metallicity: PASTEL (Soubiran et al. 2016).'
		);
		expect(rowsOf(fitted({ tier: 3, fehSource: 'assumed-solar' }))[0].tooltip).toBe(
			'Effective temperature: Gaia DR3 GSP-Phot. Luminosity: Gaia DR3 FLAME. Metallicity: assumed solar.'
		);
	});
});

describe('the centre rows', () => {
	it('give the centre as ranges', () => {
		const rows = Object.fromEntries(rowsOf(fitted({})).map((r) => [r.label, r.value]));
		expect(rows['Evolutionary stage']).toBe('Main sequence');
		expect(rows['Central temperature']).toMatch(/15M?\D+17M/);
		expect(rows['Central density']).toContain('100–200');
		expect(rows['Central hydrogen fraction']).toContain('30–50%');
		expect(rows['Central helium fraction']).toContain('50–70%');
	});

	it('are left out on tier 3', () => {
		const labels = rowsOf(
			fitted({
				tier: 3,
				fehSource: 'assumed-solar',
				centreTemperature: NONE,
				centreDensity: NONE,
				centreX: null,
				centreY: null
			})
		).map((r) => r.label);
		expect(labels).toEqual(['Model', 'Evolutionary stage']);
	});
});

describe('the layers of a star', () => {
	it('have names, the convective core of a hot star among them', () => {
		expect(layerName('convective_core')).toBe('Convective core');
		expect(layerName('convective_zone')).toBe('Convective zone');
		expect(layerName('radiative_zone')).toBe('Radiative zone');
	});
});
