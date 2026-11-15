import { afterEach, describe, expect, it, vi } from 'vitest';
import { configureHost } from '$lib/host';
import { GALAXY, galaxyExport } from '$lib/fetch/extrasolar/__fixtures__/galaxy';
import { fetchHomeGalaxy } from './home-galaxy';
import { fetchPageName } from './page-name';

vi.mock('./page-name', () => ({ fetchPageName: vi.fn() }));

const XS = 'https://xs.test';

/** An export at `base` whose `metadata.json` is `meta`. The home galaxy is
 *  kept per base: a test that counts its reads takes a base of its own. */
function serve(meta: object, base = XS) {
	configureHost({ tilesUrl: base });
	vi.stubGlobal(
		'fetch',
		vi.fn(async () => Response.json(meta))
	);
}

afterEach(() => {
	configureHost({});
	vi.unstubAllGlobals();
	vi.mocked(fetchPageName).mockReset();
});

describe('the galaxy that holds the Sun', () => {
	it('is the one that the export names, under the name of its page', async () => {
		serve(galaxyExport().meta);
		vi.mocked(fetchPageName).mockResolvedValue('Voie lactée');
		expect(await fetchHomeGalaxy()).toEqual({ id: GALAXY, name: 'Voie lactée' });
		expect(fetchPageName).toHaveBeenCalledWith({ kind: 'body', id: `x-${GALAXY}` });
	});

	it('is none where the host serves no extrasolar export', async () => {
		configureHost({});
		expect(await fetchHomeGalaxy()).toBeNull();
		expect(fetchPageName).not.toHaveBeenCalled();
	});

	it('is none in an export that names none', async () => {
		// Another base URL: `metadata.json` is kept per base.
		const { home_galaxy: named, ...meta } = galaxyExport().meta;
		expect(named).toBe(GALAXY);
		configureHost({ tilesUrl: 'https://older.test' });
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => Response.json(meta))
		);
		expect(await fetchHomeGalaxy()).toBeNull();
		expect(fetchPageName).not.toHaveBeenCalled();
	});

	it('is read once for an export and a language, however often it is asked for', async () => {
		serve(galaxyExport().meta, 'https://once.test');
		vi.mocked(fetchPageName).mockResolvedValue('Milky Way');
		const first = fetchHomeGalaxy();
		expect(fetchHomeGalaxy()).toBe(first);
		await first;
		expect(fetchHomeGalaxy()).toBe(first);
		expect(fetchPageName).toHaveBeenCalledTimes(1);
		expect(fetch).toHaveBeenCalledTimes(1);
	});

	it('is read once where the export names none', async () => {
		configureHost({});
		const first = fetchHomeGalaxy();
		expect(await first).toBeNull();
		expect(fetchHomeGalaxy()).toBe(first);
	});

	it('is read again in another language', async () => {
		serve(galaxyExport().meta, 'https://languages.test');
		vi.mocked(fetchPageName)
			.mockResolvedValueOnce('Milky Way')
			.mockResolvedValueOnce('Voie lactée');
		expect((await fetchHomeGalaxy())?.name).toBe('Milky Way');
		configureHost({ tilesUrl: 'https://languages.test', locale: () => 'fr' });
		expect((await fetchHomeGalaxy())?.name).toBe('Voie lactée');
		expect(fetchPageName).toHaveBeenCalledTimes(2);
	});

	it('does not keep a failure', async () => {
		serve(galaxyExport().meta, 'https://failing.test');
		vi.mocked(fetchPageName).mockRejectedValueOnce(new Error('offline'));
		await expect(fetchHomeGalaxy()).rejects.toThrow('offline');
		vi.mocked(fetchPageName).mockResolvedValue('Milky Way');
		expect(await fetchHomeGalaxy()).toEqual({ id: GALAXY, name: 'Milky Way' });
	});
});
