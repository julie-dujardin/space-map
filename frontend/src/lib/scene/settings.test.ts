import { describe, expect, it } from 'vitest';
import type { MapLayerId } from '$lib/scene/layers';
import { constellationsAsked, constellationsWanted } from './settings.svelte';

const page = { culture: 'modern', slug: null, opening: false, hidden: false };
const skyOn = () => true;
const skyOff = (id: MapLayerId) => id !== 'stars' && id !== 'starfield';

describe('the constellation layer', () => {
	it('is asked for by the reader or by the page, unless hidden there', () => {
		expect(constellationsAsked({ showConstellations: true, pageSky: null })).toBe(true);
		expect(constellationsAsked({ showConstellations: false, pageSky: page })).toBe(true);
		expect(
			constellationsAsked({ showConstellations: false, pageSky: { ...page, hidden: true } })
		).toBe(false);
	});

	it('draws only in the map view', () => {
		const asked = { showConstellations: true, pageSky: null };
		expect(constellationsWanted({ ...asked, viewMode: 'map' }, skyOn)).toBe(true);
		expect(constellationsWanted({ ...asked, viewMode: 'immersive' }, skyOn)).toBe(false);
	});

	it('needs a sky: the skybox or the starfield', () => {
		const asked = { showConstellations: true, pageSky: null, viewMode: 'map' } as const;
		expect(constellationsWanted(asked, skyOff)).toBe(false);
		expect(constellationsWanted(asked, (id) => id === 'starfield')).toBe(true);
	});
});
