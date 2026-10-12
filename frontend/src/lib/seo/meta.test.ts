import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { gzipSync } from 'node:zlib';

// As on the server: a path is relative to the request, and each request here
// is three segments deep.
vi.mock('$app/paths', () => ({
	resolve: (route: string, params: Record<string, string | undefined>) =>
		'../..' +
		route
			.replace('[type]', params.type ?? '')
			.replace('[id]', params.id ?? '')
			.replace('[featureId]', params.featureId ?? '')
			.replace('/[[name]]', params.name ? `/${params.name}` : '')
}));

import { configureHost } from '$lib/host';
import { catalogueSeo, loadGroupSeo, loadObjectSeo, minimalSeo } from './meta';

const ORIGIN = 'https://spacemap.test';
/** A request for the page: the name in it is not the export's. */
const request = (path: string) => new URL(`${ORIGIN}${path}/Planet%20Nine%20Found`);
const DATA = 'https://data.test';

const gz = (value: unknown) => new Response(gzipSync(JSON.stringify(value)));

/** An export with one object and one group, in one bucket each. A path it
 *  does not list is a 404, as on the CDN. */
function stubExport(files: Record<string, () => Response>) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async (input: string) => {
			const path = new URL(input).pathname;
			return files[path]?.() ?? new Response('', { status: 404 });
		})
	);
}

const METADATA = {
	object_bundles: { global: 1, en: 1 },
	group_bundles: { global: 1, en: 1 }
};

const EXPORT: Record<string, () => Response> = {
	'/v1/metadata.json': () => Response.json(METADATA),
	'/v1/objects/__global__/0.json.gz': () => gz({ 'naif-399': { name: 'Earth', type: 'planet' } }),
	'/v1/objects/en/0.json.gz': () =>
		gz({ 'naif-399': { name: 'Earth', description: 'third planet' } }),
	'/v1/groups/__global__/0.json.gz': () => gz({ 'const-starlink': {} }),
	'/v1/groups/en/0.json.gz': () => gz({ 'const-starlink': { name: 'Starlink' } })
};

beforeEach(() => {
	configureHost({ dataUrl: DATA });
});
afterEach(() => {
	vi.unstubAllGlobals();
	configureHost({});
});

describe('loadObjectSeo', () => {
	it('names the object and its canonical link as the export does', async () => {
		stubExport(EXPORT);
		expect(await loadObjectSeo('naif-399', request('/b/399'))).toMatchObject({
			title: 'Earth - Space Map',
			description: 'Third planet',
			canonical: `${ORIGIN}/b/399/Earth`
		});
	});

	it('names it in the language of the request', async () => {
		stubExport({
			...EXPORT,
			'/v1/metadata.json': () => Response.json({ object_bundles: { global: 1, en: 1, fr: 1 } }),
			'/v1/objects/fr/0.json.gz': () => gz({ 'naif-399': { name: 'Terre' } })
		});
		configureHost({ dataUrl: DATA, locale: () => 'fr' });
		expect(await loadObjectSeo('naif-399', request('/b/399'))).toMatchObject({
			title: 'Terre - Space Map',
			canonical: `${ORIGIN}/b/399/Terre`
		});
	});

	it('names the page of a barycenter after the system of its primary', async () => {
		stubExport({
			...EXPORT,
			'/v1/objects/__global__/0.json.gz': () =>
				gz({
					'naif-5': { name: 'Jupiter Barycenter', type: 'barycenter' },
					'naif-599': { name: 'Jupiter', type: 'planet' }
				})
		});
		expect(await loadObjectSeo('naif-5', request('/b/5'))).toMatchObject({
			title: 'Jupiter system - Space Map',
			canonical: `${ORIGIN}/b/5/Jupiter%20system`
		});
	});

	it('is null for an object the export does not hold', async () => {
		stubExport(EXPORT);
		expect(await loadObjectSeo('naif-99999999', request('/b/99999999'))).toBeNull();
	});

	it('throws when a bucket the metadata counts is not there', async () => {
		// An export in the middle of an upload: the object is not known to be absent.
		stubExport({
			...EXPORT,
			'/v1/objects/__global__/0.json.gz': () => new Response('', { status: 404 })
		});
		await expect(loadObjectSeo('naif-399', request('/b/399'))).rejects.toThrow('is missing');
	});

	it('throws when the export cannot be read', async () => {
		stubExport({ ...EXPORT, '/v1/metadata.json': () => new Response('', { status: 503 }) });
		await expect(loadObjectSeo('naif-399', request('/b/399'))).rejects.toThrow('503');
		stubExport({
			...EXPORT,
			'/v1/objects/__global__/0.json.gz': () => new Response('', { status: 500 })
		});
		await expect(loadObjectSeo('naif-399', request('/b/399'))).rejects.toThrow('500');
	});
});

describe('loadGroupSeo', () => {
	it('is null for a slug the export does not hold', async () => {
		stubExport(EXPORT);
		expect(await loadGroupSeo('const-nope', request('/g/const-nope'))).toBeNull();
		expect(await loadGroupSeo('const-starlink', request('/g/const-starlink'))).toMatchObject({
			title: 'Starlink - Space Map',
			canonical: `${ORIGIN}/g/const-starlink/Starlink`
		});
	});
});

describe('catalogueSeo', () => {
	const url = request('/b/399');
	const found = minimalSeo(url, '/b/399');

	it('hands the meta through', async () => {
		expect(await catalogueSeo(Promise.resolve(found), url, '/b/399')).toBe(found);
	});

	it('answers 404 for a subject the export does not hold', async () => {
		await expect(catalogueSeo(Promise.resolve(null), url, '/b/399')).rejects.toMatchObject({
			status: 404
		});
	});

	it('opens the page on bare meta when the export cannot be read', async () => {
		vi.spyOn(console, 'warn').mockImplementation(() => {});
		const seo = await catalogueSeo(Promise.reject(new Error('503')), url, '/b/399');
		expect(seo).toEqual({
			title: 'Space Map',
			description: 'Space Map, an interactive 3D map of the solar system.',
			canonical: `${ORIGIN}/b/399`,
			ogType: 'website'
		});
	});
});
