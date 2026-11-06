import { describe, expect, it, vi } from 'vitest';
import type { Planet } from '$lib/fetch/extrasolar/planets';
import { sceneSettings } from '$lib/scene/settings.svelte';
import { drawnPlanet, drawnPlanetIds, planetDraws } from './drawn';
import { elements, planet } from './__fixtures__/system';

/** The one rule for which planets of other stars draw, and its two readers. */

const texture = { source: 's', organisation: 'NASA', type: 'cylindrical', artist_impression: true };
const ID = 'x-27424668-b-1';
const mapped = (extra: Partial<Planet> = {}, values: Planet['values'] = { radius: 0.09 }) => ({
	...planet(27424668, 1, elements(0.05), values),
	texture,
	tiers: ['low'],
	...extra
});

/** A catalogue that holds `records` by page id. */
function catalogue(records: Record<string, Planet>) {
	return {
		planet: vi.fn(async (host: number, n: number) => {
			const found = records[`x-${host}-b-${n}`];
			return found ? { planet: found, system: {} as never } : null;
		})
	};
}

describe('planetDraws', () => {
	it('draws a planet with a radius and a map it may serve', () => {
		expect(planetDraws(ID, mapped())).toBe(true);
	});

	it('leaves out a planet with no radius', () => {
		expect(planetDraws(ID, mapped({}, {}))).toBe(false);
		expect(planetDraws(ID, mapped({}, { radius: 0 }))).toBe(false);
	});

	it('leaves out a planet with no map, or one this embed may not serve', () => {
		expect(planetDraws(ID, planet(27424668, 1, elements(0.05), { radius: 0.09 }))).toBe(false);
		expect(planetDraws(ID, mapped({ tiers: [] }))).toBe(false);
		expect(planetDraws(ID, mapped({ texture: { ...texture, distribution: 'site-only' } }))).toBe(
			false
		);
	});

	it('draws a planet while surface maps are off', () => {
		sceneSettings().showSurfaceTexture = false;
		try {
			expect(planetDraws(ID, mapped())).toBe(true);
		} finally {
			sceneSettings().showSurfaceTexture = true;
		}
	});
});

describe('drawnPlanet', () => {
	it('gives the record of a planet that draws', async () => {
		const record = mapped();
		expect(await drawnPlanet(ID, catalogue({ [ID]: record }))).toBe(record);
	});

	it('gives null for a planet that does not draw', async () => {
		const bare = planet(27424668, 1, elements(0.05), { radius: 0.09 });
		expect(await drawnPlanet(ID, catalogue({ [ID]: bare }))).toBeNull();
		expect(await drawnPlanet(ID, catalogue({}))).toBeNull();
	});

	it('gives null when the record fails to load', async () => {
		const failing = { planet: vi.fn().mockRejectedValue(new Error('offline')) };
		expect(await drawnPlanet(ID, failing)).toBeNull();
	});

	it('reads no record for an id that is not a planet of another star', async () => {
		const reader = catalogue({});
		expect(await drawnPlanet('x-27424668', reader)).toBeNull();
		expect(await drawnPlanet('naif-399', reader)).toBeNull();
		expect(reader.planet).not.toHaveBeenCalled();
	});
});

describe('drawnPlanetIds', () => {
	it('keeps the credited planets that draw', async () => {
		const other = 'x-564339647-b-1';
		const reader = catalogue({
			[ID]: mapped(),
			[other]: planet(564339647, 1, elements(0.05), { radius: 0.09 })
		});
		const credits = async () => new Map([ID, other, 'naif-499', 'x-27424668'].map((k) => [k, {}]));
		expect([...(await drawnPlanetIds(reader, credits))]).toEqual([ID]);
		// Only the credited planets are read.
		expect(reader.planet).toHaveBeenCalledTimes(2);
	});
});
