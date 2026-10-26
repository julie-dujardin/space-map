import { describe, expect, it } from 'vitest';
import { HAS_EXPORT, exportMetadata, readExportJson } from './__fixtures__/export';
import { ALPHA_CEN, INDEX, MERGED_HOST } from '$lib/scene/exoplanets/__fixtures__/system';
import type { ExtrasolarMetadata, ExtrasolarPlanets } from './files';
import { ExtrasolarStaleError } from './files';
import {
	PlanetCatalogue,
	PlanetIndex,
	type PlanetIndexFile,
	type PlanetSource,
	type PlanetSystem
} from './planets';

/** The planet index loads once, the system files on demand, each checked
 *  against the token of `metadata.json`. */

const TOKEN = '0000000000000000';
const ENTRY: ExtrasolarPlanets = {
	token: TOKEN,
	index: 'planets/index.json.gz',
	system: 'planets/{key}.json.gz',
	systems: 2,
	hosts: 3,
	planets: 5,
	distribution: 'non-commercial'
};

function source(
	files: Record<string, { token: string }>,
	planets: ExtrasolarPlanets | null = ENTRY,
	allowed = true
): PlanetSource & { reads: string[] } {
	const reads: string[] = [];
	return {
		reads,
		metadata: async () => ({ planets: planets ?? undefined }) as ExtrasolarMetadata,
		json: async <T extends { token: string }>(path: string, token: string): Promise<T> => {
			reads.push(path);
			const file = files[path];
			if (!file) throw new Error(`${path} returned 404`);
			if (file.token !== token) throw new ExtrasolarStaleError(path, file.token, token);
			return file as T;
		},
		allowed: () => allowed
	};
}

const FILES = { 'planets/index.json.gz': INDEX, 'planets/27424668.json.gz': ALPHA_CEN };

describe('PlanetIndex', () => {
	const index = new PlanetIndex(INDEX);

	it('finds a host, and the hosts of a system file', () => {
		expect(index.host(564339647)?.system).toBe(27424668);
		expect(index.host(5)).toBeUndefined();
		expect(index.hostsOf(27424668)).toEqual([27424668, 564339647]);
		expect(index.hostsOf(5)).toEqual([]);
	});

	it('maps a page to its live planet through an alias, and the rest to no page', () => {
		expect(index.live(1091633172, 2)).toEqual({ host: 1091633172, n: 2 });
		expect(index.live(1091633172, 3)).toEqual({ host: 1091633172, n: 2 });
		expect(index.live(1091633172, 4)).toBeNull();
		expect(index.live(27424668, 3)).toBeNull();
		expect(index.live(5, 1)).toBeNull();
	});

	it('leads an alias of a host that merged to its planet on another host', () => {
		expect(index.host(MERGED_HOST)).toBeUndefined();
		expect(index.live(MERGED_HOST, 1)).toEqual({ host: 27424668, n: 2 });
		expect(index.live(MERGED_HOST, 2)).toBeNull();
	});
});

describe('PlanetCatalogue', () => {
	it('loads the index once and the system files by key', async () => {
		const src = source(FILES);
		const catalogue = new PlanetCatalogue(src);
		const [a, b] = await Promise.all([catalogue.index(), catalogue.index()]);
		expect(a).toBe(b);
		expect(a?.host(27424668)?.outer_orbit).toBe(1.5);
		expect((await catalogue.system(27424668)).hosts.map((h) => h.id)).toEqual([
			27424668, 564339647
		]);
		await catalogue.system(27424668);
		expect(src.reads).toEqual(['planets/index.json.gz', 'planets/27424668.json.gz']);
	});

	it('finds a planet and its system through the index, an alias too', async () => {
		const catalogue = new PlanetCatalogue(source(FILES));
		const toliman = await catalogue.planet(564339647, 1);
		expect(toliman?.planet.name).toBe('Planet 564339647 1');
		expect(toliman?.system.system).toBe(27424668);
		expect(await catalogue.planet(27424668, 9)).toBeNull();
		expect(await catalogue.planet(5, 1)).toBeNull();
		expect((await catalogue.hostSystem(564339647))?.system).toBe(27424668);
		expect(await catalogue.hostSystem(5)).toBeNull();
		// An alias number gives the live planet, whose number says it is another.
		const pulsar: PlanetSystem = {
			token: INDEX.token,
			system: 1091633172,
			hosts: [],
			planets: [{ ...ALPHA_CEN.planets[0], host: 1091633172, number: 2 }]
		};
		const aliased = new PlanetCatalogue(source({ ...FILES, 'planets/1091633172.json.gz': pulsar }));
		expect(await aliased.planet(1091633172, 3)).toMatchObject({
			planet: { host: 1091633172, number: 2 }
		});
	});

	it("follows an alias to a planet on another host, in that host's system file", async () => {
		const src = source(FILES);
		const moved = await new PlanetCatalogue(src).planet(MERGED_HOST, 1);
		expect(moved?.planet).toMatchObject({ host: 27424668, number: 2, name: 'Planet 27424668 2' });
		expect(moved?.system.system).toBe(27424668);
		expect(src.reads).toEqual(['planets/index.json.gz', 'planets/27424668.json.gz']);
	});

	it('refuses an alias to a host the index does not list', async () => {
		const broken: PlanetIndexFile = { ...INDEX, aliases: { '5/1': [6, 1] } };
		const catalogue = new PlanetCatalogue(source({ ...FILES, 'planets/index.json.gz': broken }));
		await expect(catalogue.planet(5, 1)).rejects.toThrow('host 6');
	});

	it('has no index where the export has no planets or the host may not show them', async () => {
		expect(await new PlanetCatalogue(source(FILES, null)).index()).toBeNull();
		const barred = source(FILES, ENTRY, false);
		expect(await new PlanetCatalogue(barred).index()).toBeNull();
		await expect(new PlanetCatalogue(barred).system(27424668)).rejects.toThrow();
		expect(barred.reads).toEqual([]);
	});

	it('refuses a file from another export, and tries again on the next call', async () => {
		const stale: PlanetIndexFile = { ...INDEX, token: 'ffffffffffffffff' };
		const files: Record<string, { token: string }> = { 'planets/index.json.gz': stale };
		const catalogue = new PlanetCatalogue(source(files));
		await expect(catalogue.index()).rejects.toThrow(ExtrasolarStaleError);
		files['planets/index.json.gz'] = INDEX;
		expect(await catalogue.index()).not.toBeNull();
	});

	it('keeps a few system files, and fetches one that went again', async () => {
		const files: Record<string, PlanetSystem | PlanetIndexFile> = { ...FILES };
		for (const key of [1, 2, 3]) files[`planets/${key}.json.gz`] = { ...ALPHA_CEN, system: key };
		const src = source(files);
		const catalogue = new PlanetCatalogue(src, 2);
		for (const key of [1, 2, 3, 1]) await catalogue.system(key);
		expect(src.reads.filter((p) => p === 'planets/1.json.gz')).toHaveLength(2);
	});
});

describe.skipIf(!HAS_EXPORT)('the planet files of the export', () => {
	const meta = HAS_EXPORT ? exportMetadata() : null!;
	const catalogue = new PlanetCatalogue({
		metadata: async () => meta,
		json: async <T extends { token: string }>(path: string, token: string) => {
			const value = readExportJson<T>(path);
			if (value.token !== token) throw new ExtrasolarStaleError(path, value.token, token);
			return value;
		},
		allowed: () => true
	});

	it('reads α Cen as one file with both hosts, and Proxima b by its number', async () => {
		const index = (await catalogue.index())!;
		expect(index.host(564339647)?.system).toBe(27424668);
		expect(index.host(27424668)?.planets).toContain(1);
		const file = await catalogue.system(27424668);
		expect(file.hosts.map((h) => h.id)).toEqual([27424668, 564339647]);
		const b = file.planets.find((p) => p.host === 27424668 && p.number === 1)!;
		expect(b.elements?.phase).toBe('transit');
		expect(b.elements?.n).toBeCloseTo(360 / 11.18465, 6);
	});

	it('gives a host with no distance no place', async () => {
		const index = (await catalogue.index())!;
		expect(index.host(1091633172)?.position).toBeNull();
	});
});
