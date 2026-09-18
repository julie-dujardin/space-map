/**
 * Some surface maps are ours to show on spacemap.co and nowhere else, and
 * some carry a licence that bars commercial reuse. This ladder is the one
 * place that decides whether an embed may ask the CDN for the picture, so a
 * mistake here serves a map into a page it was never cleared for.
 */

import { beforeEach, describe, expect, it } from 'vitest';

import { configureHost, pickTexture, textureAllowed } from './host';

describe('textureAllowed', () => {
	beforeEach(() => {
		// Back to what a bare embed gets; each test opts up from there.
		configureHost({});
	});

	it('allows a map that names no distribution, whoever is embedding', () => {
		expect(textureAllowed(undefined)).toBe(true);
	});

	it('refuses both restricted tiers to a bare embed', () => {
		expect(textureAllowed('non-commercial')).toBe(false);
		expect(textureAllowed('site-only')).toBe(false);
	});

	it('opens the non-commercial tier when the page asks for it', () => {
		configureHost({ textures: 'non-commercial' });
		expect(textureAllowed('non-commercial')).toBe(true);
	});

	it('keeps site-only out of an embed that took the non-commercial tier', () => {
		configureHost({ textures: 'non-commercial' });
		expect(textureAllowed('site-only')).toBe(false);
	});

	it('allows every tier on the site the site-only maps are cleared for', () => {
		configureHost({ textures: 'site-only' });
		expect(textureAllowed('non-commercial')).toBe(true);
		expect(textureAllowed('site-only')).toBe(true);
	});

	it('drops back to the bare embed when a second map configures no tier', () => {
		configureHost({ textures: 'site-only' });
		configureHost({});
		expect(textureAllowed('site-only')).toBe(false);
	});

	it('refuses a tier it does not know, which is newer than this build', () => {
		configureHost({ textures: 'site-only' });
		expect(textureAllowed('press-only')).toBe(false);
	});
});

describe('pickTexture', () => {
	beforeEach(() => {
		configureHost({});
	});

	// How the export ranks a body's maps: best first, each saying who may serve it.
	const BEST = { id: 'naif-299', distribution: 'site-only' };
	const FALLBACK = { id: 'naif-299_alt-usgs', distribution: undefined };

	it('takes the best map where the embed may serve it', () => {
		configureHost({ textures: 'site-only' });
		expect(pickTexture([BEST, FALLBACK])?.id).toBe('naif-299');
	});

	it('walks down to a map it may serve rather than going without', () => {
		expect(pickTexture([BEST, FALLBACK])?.id).toBe('naif-299_alt-usgs');
	});

	it('keeps walking past a fallback that is itself out of reach', () => {
		const middle = { id: 'naif-299_alt-nc', distribution: 'non-commercial' };
		expect(pickTexture([BEST, middle, FALLBACK])?.id).toBe('naif-299_alt-usgs');
		configureHost({ textures: 'non-commercial' });
		expect(pickTexture([BEST, middle, FALLBACK])?.id).toBe('naif-299_alt-nc');
	});

	it('gives nothing when every candidate is out of reach', () => {
		expect(pickTexture([BEST, { id: 'x', distribution: 'site-only' }])).toBeUndefined();
	});

	it('skips a candidate the payload left out', () => {
		expect(pickTexture([undefined, FALLBACK])?.id).toBe('naif-299_alt-usgs');
	});

	it('gives nothing for a body with no map at all', () => {
		expect(pickTexture([])).toBeUndefined();
	});
});
