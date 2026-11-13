/**
 * Which GLB tier a small drawing loads. A craft's two tiers are often separate
 * models rather than one decimated, so taking `low` by default cost real
 * detail; the budget only exists to keep a million-triangle mesh out of a
 * 100 px hero.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Group } from 'three';
import { configureHost } from '$lib/host';
import {
	allowedTier,
	cheapTier,
	craftTier,
	loadModelBundle,
	modelLoader,
	modelTierCredit,
	tierSpanRatio,
	type BundleTiers,
	type ModelBundleMeta,
	type ModelTierExport
} from './model';

vi.mock('$lib/fetch/data-base', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/fetch/data-base')>()),
	versionedUrl: (path: string) => path
}));

const nasa = { name: 'NASA', url: 'https://nasa.gov' };
const esa = { name: 'ESA', url: 'https://scifleet.esa.int/' };
const nonCommercial = 'non-commercial';

function bundle(withLow = true): ModelBundleMeta {
	return {
		tiers: withLow ? ['high', 'low'] : ['high'],
		exports: {
			high: { credit: esa },
			...(withLow ? { low: { credit: nasa } } : {})
		}
	};
}

/** An entry of `tiers.json`. */
function tiers(highBytes?: number, withLow = true): BundleTiers {
	return {
		high: highBytes === undefined ? {} : { size_bytes: highBytes },
		...(withLow ? { low: {} } : {})
	};
}

beforeEach(() => {
	// Back to what a bare embed gets; each test opts up from there.
	configureHost({});
});

describe('craftTier', () => {
	it('takes the best mesh, which the main scene loads too', () => {
		expect(craftTier(tiers(710_532))).toBe('high');
	});

	it('falls back once the best mesh is too heavy to be worth it', () => {
		// The ISS: 14.7 MB and a million triangles against 42 KB.
		expect(craftTier(tiers(14_720_000))).toBe('low');
	});

	it('keeps the heavy mesh when there is no cheaper one to fall back to', () => {
		expect(craftTier(tiers(14_720_000, false))).toBe('high');
	});

	it('takes the best mesh when no size is listed', () => {
		expect(craftTier(tiers())).toBe('high');
	});

	it('takes the best mesh for a bundle the list leaves out', () => {
		expect(craftTier(undefined)).toBe('high');
	});

	it('walks down to the mesh this embed may draw', () => {
		expect(craftTier({ high: { distribution: nonCommercial, size_bytes: 1 }, low: {} })).toBe(
			'low'
		);
		expect(craftTier({ high: { distribution: nonCommercial } })).toBeUndefined();
	});
});

describe('modelTierCredit', () => {
	it('credits the catalogue behind the tier actually drawn', () => {
		// Cassini's tiers come from different archives; crediting `high` while
		// drawing `low` would name the wrong one.
		const meta = bundle();
		expect(modelTierCredit(meta, 'high').name).toBe('ESA');
		expect(modelTierCredit(meta, 'low').name).toBe('NASA');
		expect(modelTierCredit(bundle(false), 'low').name).toBe('ESA');
	});
});

describe('tierSpanRatio', () => {
	const lm = (low?: number): ModelBundleMeta => ({
		tiers: ['high', 'low'],
		exports: {
			high: { credit: nasa, scale_meters: 6.9 },
			low: { credit: nasa, ...(low ? { scale_meters: low } : {}) }
		}
	});

	it("scales a low tier that is another mesh to the high tier's slot", () => {
		// The full LM's high mesh spans its box between pads on the diagonals,
		// NASA's low mesh from pad to pad on the axes.
		expect(tierSpanRatio(lm(9.4), 'low')).toBeCloseTo(9.4 / 6.9);
		expect(tierSpanRatio(lm(9.4), 'high')).toBe(1);
	});

	it('leaves a tier with no span of its own as it is', () => {
		expect(tierSpanRatio(lm(), 'low')).toBe(1);
		expect(tierSpanRatio(bundle(), 'low')).toBe(1);
	});
});

describe('cheapTier', () => {
	it('is what a shape model takes: the same surface, decimated', () => {
		expect(cheapTier(tiers(1_593_000))).toBe('low');
		expect(cheapTier(tiers(1_593_000, false))).toBe('high');
		// DAMIT bundles are not in the list, and ship `high` only.
		expect(cheapTier(undefined)).toBe('high');
	});
});

describe('allowedTier', () => {
	it('draws the best mesh when no licence restricts it', () => {
		// Such a bundle is not in the list at all.
		expect(allowedTier(undefined)).toBe('high');
	});

	it('walks down to an open mesh in an embed that accepted no licence', () => {
		// Mir: the detailed mesh is CC BY-NC, the plain one is NASA's.
		expect(allowedTier({ high: { distribution: nonCommercial }, low: {} })).toBe('low');
	});

	it('draws nothing when the only mesh bars commercial reuse', () => {
		expect(allowedTier({ high: { distribution: nonCommercial } })).toBeUndefined();
	});

	it('draws nothing when both meshes bar commercial reuse', () => {
		const nc = { distribution: nonCommercial };
		expect(allowedTier({ high: nc, low: nc })).toBeUndefined();
	});

	it('draws the non-commercial mesh once the page accepts its terms', () => {
		configureHost({ textures: 'non-commercial' });
		const nc = { distribution: nonCommercial };
		expect(allowedTier({ high: nc, low: {} })).toBe('high');
		expect(allowedTier({ high: nc, low: nc })).toBe('high');
	});

	it('refuses a tier newer than this build rather than guessing', () => {
		expect(allowedTier({ high: { distribution: 'partners-only' }, low: {} })).toBe('low');
	});
});

describe('loadModelBundle', () => {
	afterEach(() => vi.restoreAllMocks());

	/** GLBs whose payloads say what the URL's tier may be drawn by. */
	function serve(exports: { high: ModelTierExport; low?: ModelTierExport }) {
		const meta: ModelBundleMeta = { tiers: Object.keys(exports), exports };
		return vi.spyOn(modelLoader, 'loadAsync').mockImplementation(
			async () =>
				({
					scene: new Group(),
					asset: { version: '2.0', extras: { spacemap: meta } }
				}) as unknown as Awaited<ReturnType<typeof modelLoader.loadAsync>>
		);
	}

	const open: ModelTierExport = { credit: nasa };
	const restricted: ModelTierExport = { credit: esa, distribution: nonCommercial };

	it('draws the tier asked for when its payload allows it', async () => {
		serve({ high: open });
		expect((await loadModelBundle('a', 'high'))?.tier).toBe('high');
	});

	it('trusts the payload over the list: a barred tier gives way to an open one', async () => {
		const load = serve({ high: restricted, low: open });
		const loaded = await loadModelBundle('mir', 'high');
		expect(loaded?.tier).toBe('low');
		expect(load.mock.calls.map((c) => c[0])).toEqual([
			'/v1/models/mir/high.glb',
			'/v1/models/mir/low.glb'
		]);
	});

	it('draws nothing when no tier is this page to draw', async () => {
		serve({ high: restricted });
		expect(await loadModelBundle('teapot', 'high')).toBeNull();
	});

	it('draws a barred tier once the page accepts its terms', async () => {
		configureHost({ textures: 'non-commercial' });
		serve({ high: restricted, low: open });
		expect((await loadModelBundle('mir', 'high'))?.tier).toBe('high');
	});
});
