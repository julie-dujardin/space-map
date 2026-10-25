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
import {
	catalogueSeo,
	configureSeoPages,
	loadFeatureSeo,
	loadGroupSeo,
	loadObjectSeo,
	loadStarSeo,
	minimalSeo
} from './meta';
import {
	ALIAS,
	RETIRED,
	SECOND,
	STAR,
	syntheticExport
} from '$lib/fetch/extrasolar/__fixtures__/synthetic';

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
	configureSeoPages(null);
});

/** The site's static assets, holding these page records. */
function stubPages(records: Record<string, unknown>) {
	configureSeoPages(async (path) => {
		const key = path.replace(/^\/_seo\//, '').replace(/\.json$/, '');
		return key in records ? Response.json(records[key]) : new Response('', { status: 404 });
	});
}

const EARTH_RECORD = {
	v: 'img1',
	global: {
		name: 'Earth',
		type: 'planet',
		images: [{ file: 'Earth.jpg', kind: 'photo', attr: 'free', variants: { m: 'webp' } }]
	},
	localized: { en: { name: 'Earth', description: 'third planet' }, fr: { name: 'Terre' } },
	credits: {}
};

describe('page records', () => {
	it('builds the meta of a page from its record, without the export', async () => {
		stubExport({});
		stubPages({ 'o/naif-399': EARTH_RECORD });
		expect(await loadObjectSeo('naif-399', request('/b/399'))).toEqual({
			title: 'Earth - Space Map',
			description: 'Third planet',
			canonical: `${ORIGIN}/b/399/Earth`,
			image: 'https://images.spacemap.co/v1/images/Earth.jpg/m.webp?v=img1',
			ogType: 'article'
		});
		expect(fetch).not.toHaveBeenCalled();
	});

	it('names the page in the language of the request', async () => {
		stubPages({ 'o/naif-399': EARTH_RECORD });
		configureHost({ dataUrl: DATA, locale: () => 'fr' });
		expect(await loadObjectSeo('naif-399', request('/b/399'))).toMatchObject({
			title: 'Terre - Space Map',
			canonical: `${ORIGIN}/b/399/Terre`
		});
	});

	it('credits a card image from the record', async () => {
		stubExport({});
		stubPages({
			'o/naif-499': {
				global: {
					name: 'Mars',
					type: 'planet',
					images: [{ file: 'Mars.png', kind: 'photo', attr: 'credit', variants: { m: 'webp' } }]
				},
				localized: { en: { name: 'Mars', description: 'fourth planet' } },
				credits: { 'Mars.png': { license: { name: 'CC BY 4.0' }, artist: 'Kevin M. Gill' } }
			}
		});
		const seo = await loadObjectSeo('naif-499', request('/b/499'));
		expect(seo?.description).toBe('Image: Kevin M. Gill (CC BY 4.0). Fourth planet');
		expect(seo?.image).toBe('https://images.spacemap.co/v1/images/Mars.png/m.webp');
	});

	it('reads the export for a page that has no record', async () => {
		stubExport(EXPORT);
		stubPages({});
		expect(await loadObjectSeo('naif-399', request('/b/399'))).toMatchObject({
			title: 'Earth - Space Map',
			description: 'Third planet'
		});
	});

	it('names a feature from its record', async () => {
		stubExport({});
		stubPages({
			'f/naif-301/7': {
				global: { origin: 'Tycho Brahe, Danish astronomer' },
				localized: {},
				credits: {},
				names: { en: 'Tycho' }
			}
		});
		expect(await loadFeatureSeo('naif-301', 7, request('/b/301/f/7'))).toMatchObject({
			title: 'Tycho - Space Map',
			description: 'Tycho Brahe, Danish astronomer.'
		});
	});

	it('names a group from its record', async () => {
		stubExport({});
		stubPages({
			'g/const-starlink': { global: {}, localized: { en: { name: 'Starlink' } }, credits: {} }
		});
		expect(await loadGroupSeo('const-starlink', request('/g/const-starlink'))).toMatchObject({
			title: 'Starlink - Space Map',
			canonical: `${ORIGIN}/g/const-starlink/Starlink`
		});
	});
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

describe('loadStarSeo', () => {
	const XS = 'https://xs.test';

	/** The object entry of STAR, whose Metadata row has `object`. */
	const STAR_ENTRY: Record<string, () => Response> = {
		'/v1/metadata.json': () => Response.json(METADATA),
		'/v1/objects/__global__/0.json.gz': () =>
			gz({ [`x-${STAR}`]: { id: `x-${STAR}`, type: 'star', name: 'Test Star' } }),
		'/v1/objects/en/0.json.gz': () =>
			gz({ [`x-${STAR}`]: { name: 'Teststern', description: 'star near the Sun' } })
	};

	/** The synthetic extrasolar export at XS, and the object entries at DATA;
	 *  `broken` paths answer 503, and all of DATA with `entryDown`. */
	function stubStars(
		options: {
			metaDistribution?: string;
			broken?: string[];
			stale?: string;
			entryDown?: boolean;
		} = {}
	) {
		const { meta, payloads } = syntheticExport(options);
		vi.stubGlobal(
			'fetch',
			vi.fn(async (input: string) => {
				const url = new URL(input);
				if (url.origin === DATA) {
					if (options.entryDown) return new Response('', { status: 503 });
					return STAR_ENTRY[url.pathname]?.() ?? new Response('', { status: 404 });
				}
				expect(url.origin).toBe(XS);
				const path = url.pathname.replace(/^\/v1\/x\//, '');
				if (options.broken?.includes(path)) return new Response('', { status: 503 });
				if (path === 'metadata.json') return Response.json(meta);
				const payload = payloads[path];
				if (!payload) return new Response('', { status: 404 });
				const bytes = Uint8Array.from(payload);
				if (options.stale === path) bytes.set(new TextEncoder().encode('f'.repeat(16)), 8);
				return new Response(gzipSync(bytes));
			})
		);
	}

	beforeEach(() => configureHost({ dataUrl: DATA, extrasolarUrl: XS, textures: 'site-only' }));

	it('takes the title and canonical link from the Metadata row', async () => {
		stubStars();
		const page = await loadStarSeo(String(SECOND), request(`/x/${SECOND}`));
		expect(page).toEqual({
			kind: 'page',
			seo: {
				title: `Star ${SECOND} - Space Map`,
				description: expect.stringContaining(`Star ${SECOND}`),
				canonical: `${ORIGIN}/x/${SECOND}/Star%20${SECOND}`,
				ogType: 'article'
			}
		});
		// The Metadata table alone: no data table and no object entry is read.
		const urls = vi.mocked(fetch).mock.calls.map(([input]) => new URL(String(input)));
		expect(urls.some((u) => u.pathname.includes('point-source'))).toBe(false);
		expect(urls.some((u) => u.origin === DATA)).toBe(false);
	});

	it('takes the name and the Wikidata description of its object entry', async () => {
		stubStars();
		const page = await loadStarSeo(String(STAR), request(`/x/${STAR}`));
		expect(page).toEqual({
			kind: 'page',
			seo: {
				title: 'Teststern - Space Map',
				description: 'Star near the Sun',
				canonical: `${ORIGIN}/x/${STAR}/Teststern`,
				ogType: 'article'
			}
		});
	});

	it('takes the Metadata row when its object entry does not load', async () => {
		stubStars({ entryDown: true });
		vi.spyOn(console, 'warn').mockImplementation(() => {});
		const page = await loadStarSeo(String(STAR), request(`/x/${STAR}`));
		expect(page).toEqual({
			kind: 'page',
			seo: {
				title: 'Test Star - Space Map',
				description: expect.stringContaining('Test Star'),
				canonical: `${ORIGIN}/x/${STAR}/Test%20Star`,
				ogType: 'article'
			}
		});
	});

	it('takes its card image from its page record, without the bundles', async () => {
		stubStars();
		stubPages({
			[`o/x-${STAR}`]: {
				v: 'img1',
				global: {
					name: 'Test Star',
					type: 'star',
					images: [{ file: 'Star.jpg', kind: 'photo', attr: 'free', variants: { m: 'webp' } }]
				},
				localized: { en: { description: 'star near the Sun' } },
				credits: {}
			}
		});
		const page = await loadStarSeo(String(STAR), request(`/x/${STAR}`));
		expect(page).toMatchObject({
			kind: 'page',
			seo: {
				title: 'Test Star - Space Map',
				description: 'Star near the Sun',
				image: expect.stringContaining('/v1/images/Star.jpg/m.webp?v=img1')
			}
		});
		const urls = vi.mocked(fetch).mock.calls.map(([input]) => new URL(String(input)));
		expect(urls.some((u) => u.origin === DATA)).toBe(false);
	});

	it("sends an alias to its live ID's page, query and all", async () => {
		stubStars();
		const url = new URL(`${ORIGIN}/x/${ALIAS}/Old?at=now,1,2,3`);
		expect(await loadStarSeo(String(ALIAS), url)).toEqual({
			kind: 'alias',
			location: `/x/${STAR}/Test%20Star?at=now,1,2,3`
		});
	});

	it('has no page for a retired ID, or where the host may not show the table', async () => {
		stubStars();
		expect(await loadStarSeo(String(RETIRED), request(`/x/${RETIRED}`))).toBeNull();
		configureHost({ dataUrl: DATA, extrasolarUrl: XS, textures: 'open' });
		stubStars({ metaDistribution: 'non-commercial' });
		expect(await loadStarSeo(String(STAR), request(`/x/${STAR}`))).toBeNull();
	});

	it('throws where the export cannot be read, or a file is from another export', async () => {
		stubStars({ broken: ['metadata.json'] });
		await expect(loadStarSeo(String(STAR), request(`/x/${STAR}`))).rejects.toThrow();
		stubStars({ stale: 'metadata/0/0.bin.gz' });
		await expect(loadStarSeo(String(STAR), request(`/x/${STAR}`))).rejects.toThrow('token');
	});
});
