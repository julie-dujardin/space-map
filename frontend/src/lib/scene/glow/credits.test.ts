import { afterEach, describe, expect, it, vi } from 'vitest';
import { configureHost } from '$lib/host';
import { inSceneCredits } from '$lib/fetch/extrasolar/files';
import { nestCredits, type NestCredit, type NestMetadata } from '$lib/scene/dust/nest';
import { eachSourceOnce, fetchGlowCredits, glowCredits } from './credits';
import { fetchGlowMetadata } from './grid';

const paper = (key: string, citation: string, license: string | null = null): NestCredit => ({
	key,
	name: `${key} work`,
	citation,
	source: `https://example.org/${key}`,
	license,
	distribution: 'open'
});

const shape = paper('reid-2019', 'Reid et al. 2019, arXiv:1910.03357');
const model = paper('lian-2024', 'Lian et al. 2024, arXiv:2406.05604');
const dataset = paper('lvdb', 'Pace 2025, OJAp 8, 142', 'CC0 1.0');
const META = {
	format: 1,
	token: '0123456789abcdef',
	distribution: 'open',
	credits: [shape, model, dataset]
};

afterEach(() => {
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
	configureHost({});
});

describe('glowCredits', () => {
	it('maps every entry as the nest does', () => {
		const expected = nestCredits({ credits: [shape, model, dataset] } as NestMetadata);
		expect(glowCredits(META)).toEqual(expected);
	});

	it('keeps the papers and datasets of the model off the credit bar', () => {
		const credits = glowCredits(META);
		expect(credits.map((credit) => credit.organisation)).toEqual([
			'Reid et al. 2019',
			'Lian et al. 2024',
			'Pace 2025'
		]);
		expect(credits.some(inSceneCredits)).toBe(false);
		expect(credits[2].license).toBe('CC0 1.0');
	});

	it('keeps the emission’s datasets, with no licence stated, off the credit bar too', () => {
		const wise = paper('wise-hii-v3', 'Anderson et al. 2014, arXiv:1312.6202');
		const mccallum = paper('mccallum-2025', 'McCallum et al. 2025, arXiv:2503.14348', 'CC BY 4.0');
		const credits = glowCredits({ credits: [...META.credits, mccallum, wise] });
		expect(credits.map((credit) => credit.organisation).slice(3)).toEqual([
			'McCallum et al. 2025',
			'Anderson et al. 2014'
		]);
		expect(credits[4].license).toBeUndefined();
		expect(credits.some(inSceneCredits)).toBe(false);
	});
});

let hosts = 0;

/** Each call serves from a base URL of its own, so no test reads the metadata another one kept. */
function serve(status: number, body: unknown = META) {
	configureHost({ extrasolarUrl: `https://data${++hosts}.example` });
	const fetch = vi.fn(async () => new Response(JSON.stringify(body), { status }));
	vi.stubGlobal('fetch', fetch);
	return fetch;
}

describe('fetchGlowCredits', () => {
	it('reads the credits of v1/glow/', async () => {
		const fetch = serve(200);
		const credits = await fetchGlowCredits();
		expect(credits.map((credit) => credit.source)).toEqual([
			shape.source,
			model.source,
			dataset.source
		]);
		expect(String((fetch.mock.calls[0] as unknown[])[0])).toContain('/v1/glow/metadata.json');
	});

	it('is empty with no warning where the host has no glow', async () => {
		serve(404);
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		expect(await fetchGlowCredits()).toEqual([]);
		expect(warn).not.toHaveBeenCalled();
	});

	it('is empty with a warning for a format it cannot read', async () => {
		serve(200, { ...META, format: 2 });
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		expect(await fetchGlowCredits()).toEqual([]);
		expect(warn).toHaveBeenCalledOnce();
	});

	it('shares one request with the scene', async () => {
		const fetch = serve(200, { ...META, table: { magnitudes: [-20, -19.5] } });
		await fetchGlowCredits();
		await fetchGlowMetadata();
		expect(fetch).toHaveBeenCalledTimes(1);
	});
});

describe('eachSourceOnce', () => {
	it('lists a paper of the nest and the model once, where the nest lists it', () => {
		const nest = nestCredits({
			credits: [paper('planck-2013', 'Planck 2014'), shape]
		} as NestMetadata);
		const merged = eachSourceOnce([...nest, ...glowCredits(META)]);
		expect(merged.map((credit) => credit.source)).toEqual([
			'https://example.org/planck-2013',
			shape.source,
			model.source,
			dataset.source
		]);
	});
});
