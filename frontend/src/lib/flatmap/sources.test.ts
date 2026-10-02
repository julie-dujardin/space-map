import { describe, expect, it } from 'vitest';
import { bestTier, fromRecord, lowerTier, tierForWidth } from './sources';

describe('choosing a resolution tier', () => {
	it('takes the smallest tier that covers the width on screen', () => {
		expect(tierForWidth(900)).toBe('low');
		expect(tierForWidth(2048)).toBe('low');
		expect(tierForWidth(4096)).toBe('medium');
		expect(tierForWidth(9000)).toBe('high');
	});

	it('takes the largest tier there is for a width past all of them', () => {
		expect(tierForWidth(40000)).toBe('high');
	});

	it('takes the coarser of two tiers', () => {
		expect(lowerTier('high', 'medium')).toBe('medium');
		expect(lowerTier('low', 'high')).toBe('low');
	});

	it('never asks for a tier the bundle does not have', () => {
		expect(bestTier(['low', 'medium'], 'high')).toBe('medium');
		expect(bestTier(['low'], 'medium')).toBe('low');
	});
});

describe('a body outside every system file', () => {
	const texture = { source: 'https://example.org', organisation: 'NASA', type: 'cylindrical' };
	const tiers = async () => ['low', 'medium'];

	it('reads its map off its own record', async () => {
		const sources = await fromRecord(
			'naif-2000001',
			{ map_texture_available: true, texture, radii: { a: 483, b: 481, c: 446 } },
			tiers
		);
		expect(sources.surface).toMatchObject({ id: 'naif-2000001', tiers: ['low', 'medium'] });
		expect(sources.radiusKm).toBeCloseTo(470, 0);
	});

	it('has none when the record says so, or names no file that exists', async () => {
		expect(await fromRecord('x', null, tiers)).toEqual({});
		expect(await fromRecord('x', { map_texture_available: false, texture }, tiers)).toEqual({});
		expect(await fromRecord('x', { map_texture_available: true, texture }, async () => [])).toEqual(
			{}
		);
	});

	it('walks down to a map this viewer may serve', async () => {
		const sources = await fromRecord(
			'x',
			{
				map_texture_available: true,
				texture: { ...texture, distribution: 'site-only' },
				alternates: [{ ...texture, id: 'x_alt-usgs', tiers: ['low'] }]
			},
			tiers
		);
		expect(sources.surface).toMatchObject({ id: 'x_alt-usgs', tiers: ['low'] });
	});
});
