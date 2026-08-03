import { describe, it, expect } from 'vitest';
import { crossSection, bandPath, spreadLabels } from './interior-cross-section';
import { atmosphereProfile, drawableTopKm } from './atmosphere-cross-section';
import type { InteriorLayer, AtmosphereStructure } from '$lib/fetch/objects/object-data';

/** Europa, as the pipeline ships it. */
const EUROPA: InteriorLayer[] = [
	{ role: 'ice_shell', outer_radius_km: 1560.8, composition: [{ material: 'water', share: 1 }] },
	{ role: 'ocean', outer_radius_km: 1536.5, composition: [{ material: 'water', share: 1 }] },
	{ role: 'mantle', outer_radius_km: 1462.4, composition: [{ material: 'silicate', share: 1 }] },
	{ role: 'core', outer_radius_km: 460.3, composition: [{ material: 'metal', share: 1 }] }
];

/** Earth's stack, cut to what the geometry cares about. */
const EARTH_AIR: AtmosphereStructure = {
	datum: 'surface',
	layers: [
		{ role: 'troposphere', top_km: 11 },
		{ role: 'stratosphere', top_km: 47 },
		{ role: 'mesosphere', top_km: 84.85 },
		{ role: 'thermosphere', top_km: 600 },
		{ role: 'exosphere', top_km: 10000 }
	]
};

describe('interior cross-section', () => {
	it('nests every layer without a gap', () => {
		const section = crossSection(EUROPA)!;
		expect(section.bands).toHaveLength(4);
		for (let i = 0; i + 1 < section.bands.length; i++) {
			expect(section.bands[i].inner).toBe(section.bands[i + 1].outer);
		}
	});

	it('closes on the surface and on the centre', () => {
		const section = crossSection(EUROPA)!;
		expect(section.bands[0].outer).toBe(1);
		expect(section.bands.at(-1)!.inner).toBe(0);
	});

	it('normalizes to the outermost layer rather than to a body radius', () => {
		// Europa's exported mean radius is 1565 km; this model's R is 1560.8.
		// Against the wrong one the ice shell would stop short of the surface.
		const section = crossSection(EUROPA)!;
		expect(section.radiusKm).toBe(1560.8);
		expect(section.bands[2].outer).toBeCloseTo(1462.4 / 1560.8, 6);
	});

	it('colours a layer by its dominant material', () => {
		const section = crossSection(EUROPA)!;
		expect(section.bands[0].color).toBe('var(--material-water)');
		expect(section.bands[3].color).toBe('var(--material-metal)');
	});

	it('draws the atmosphere strip to the same scale as the body', () => {
		const section = crossSection(EUROPA, { atmosphereKm: 84.85, hasOwnAtmosphere: false })!;
		expect(section.atmosphere!.height).toBeCloseTo(84.85 / 1560.8, 6);
		expect(section.atmosphere!.km).toBe(84.85);
	});

	it('gives a giant no strip, because its outer layer already is one', () => {
		const section = crossSection(EUROPA, { atmosphereKm: 320, hasOwnAtmosphere: true })!;
		expect(section.atmosphere).toBeNull();
	});

	it('has nothing to draw without layers', () => {
		expect(crossSection([])).toBeNull();
	});

	it('closes the innermost band on the centre rather than leaving a hole', () => {
		expect(bandPath({ outer: 1, inner: 0 }, 0, 0, 10)).toContain('M 0 0 L 10 0');
		expect(bandPath({ outer: 1, inner: 0.5 }, 0, 0, 10)).toContain('M 5 0 L 10 0');
	});
});

describe('label spreading', () => {
	it('leaves labels alone when they already clear each other', () => {
		expect(spreadLabels([10, 50, 90], 20, 0, 200)).toEqual([10, 50, 90]);
	});

	it('opens a gap where two would overlap', () => {
		// Europa's 24 km ice shell over a 74 km ocean: three labels on one pixel.
		const out = spreadLabels([40, 42, 44], 20, 0, 200);
		for (let i = 1; i < out.length; i++) expect(out[i] - out[i - 1]).toBeGreaterThanOrEqual(20);
	});

	it('keeps the stack inside its bounds', () => {
		const out = spreadLabels([150, 152, 154], 25, 10, 190);
		expect(out[0]).toBeGreaterThanOrEqual(10);
		expect(out.at(-1)).toBeLessThanOrEqual(190);
		for (let i = 1; i < out.length; i++) expect(out[i] - out[i - 1]).toBeGreaterThanOrEqual(25);
	});

	it('preserves order, so a label never crosses its neighbour', () => {
		const out = spreadLabels([5, 6, 7, 8, 120], 30, 0, 200);
		expect([...out].sort((a, b) => a - b)).toEqual(out);
	});
});

describe('atmosphere cross-section', () => {
	it('scales to the highest layer that is not capped', () => {
		expect(drawableTopKm(EARTH_AIR)).toBe(84.85);
		expect(atmosphereProfile(EARTH_AIR)!.scaleKm).toBe(84.85);
	});

	it('stacks bottom-up with no gap and fills the chart', () => {
		const bands = atmosphereProfile(EARTH_AIR)!.bands;
		expect(bands[0].base).toBe(0);
		for (let i = 0; i + 1 < bands.length; i++) {
			expect(bands[i].top).toBeCloseTo(bands[i + 1].base, 10);
		}
		expect(bands.at(-1)!.top).toBeCloseTo(1, 10);
	});

	it('caps the thermosphere and exosphere to equal bands', () => {
		const bands = atmosphereProfile(EARTH_AIR)!.bands;
		const capped = bands.filter((b) => b.capped);
		expect(capped.map((b) => b.layer.role)).toEqual(['thermosphere', 'exosphere']);
		// Drawn to scale, the exosphere alone would be 99% of the chart.
		for (const band of capped) expect(band.top - band.base).toBeCloseTo(0.11, 10);
	});

	it('keeps the troposphere readable, which is the whole point of the cap', () => {
		const troposphere = atmosphereProfile(EARTH_AIR)!.bands[0];
		expect(troposphere.top).toBeGreaterThan(0.09);
	});

	it('falls back to a scale height where there are no boundaries', () => {
		// Callisto: one exosphere, no top anyone has placed.
		const profile = atmosphereProfile({
			datum: 'surface',
			layers: [{ role: 'exosphere' }],
			scale_height_km: 23
		})!;
		expect(profile.bands).toHaveLength(0);
		expect(profile.scaleHeightKm).toBe(23);
	});

	it('draws nothing for an exosphere with no scale height either', () => {
		expect(atmosphereProfile({ datum: 'surface', layers: [{ role: 'exosphere' }] })).toBeNull();
	});

	it('thins with height', () => {
		const bands = atmosphereProfile(EARTH_AIR)!.bands;
		for (let i = 0; i + 1 < bands.length; i++) {
			expect(bands[i].opacity).toBeGreaterThan(bands[i + 1].opacity);
		}
	});

	it('handles a stellar stack, where the corona is the capped one', () => {
		const sun: AtmosphereStructure = {
			datum: 'photosphere',
			layers: [
				{ role: 'photosphere', top_km: 500 },
				{ role: 'chromosphere', top_km: 2500 },
				{ role: 'transition_region', top_km: 2700 },
				{ role: 'corona', note: 'diffuse_top' }
			]
		};
		const profile = atmosphereProfile(sun)!;
		expect(profile.scaleKm).toBe(2700);
		expect(profile.bands.filter((b) => b.capped).map((b) => b.layer.role)).toEqual(['corona']);
		expect(profile.bands.at(-1)!.top).toBeCloseTo(1, 10);
	});
});
