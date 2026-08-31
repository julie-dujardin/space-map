/**
 * Which GLB tier a small drawing loads. A craft's two tiers are often separate
 * models rather than one decimated, so taking `low` by default cost real
 * detail; the budget only exists to keep a million-triangle mesh out of a
 * 100 px hero.
 */

import { describe, expect, it } from 'vitest';
import { cheapTier, craftTier, modelTierCredit, type ModelBundleMeta } from './model';

const nasa = { name: 'NASA', url: 'https://nasa.gov' };
const esa = { name: 'ESA', url: 'https://scifleet.esa.int/' };

function bundle(highBytes: number, withLow = true): ModelBundleMeta {
	return {
		tiers: withLow ? ['high', 'low'] : ['high'],
		exports: {
			high: { credit: esa, size_bytes: highBytes },
			...(withLow ? { low: { credit: nasa, size_bytes: 300_592 } } : {})
		}
	};
}

describe('craftTier', () => {
	it('takes the best mesh, which the main scene loads too', () => {
		expect(craftTier(bundle(710_532))).toBe('high');
	});

	it('falls back once the best mesh is too heavy to be worth it', () => {
		// The ISS: 14.7 MB and a million triangles against 42 KB.
		expect(craftTier(bundle(14_720_000))).toBe('low');
	});

	it('keeps the heavy mesh when there is no cheaper one to fall back to', () => {
		expect(craftTier(bundle(14_720_000, false))).toBe('high');
	});

	it('takes the best mesh when the bundle states no size', () => {
		const meta = bundle(0);
		delete meta.exports.high.size_bytes;
		expect(craftTier(meta)).toBe('high');
	});
});

describe('modelTierCredit', () => {
	it('credits the catalogue behind the tier actually drawn', () => {
		// Cassini's tiers come from different archives; crediting `high` while
		// drawing `low` would name the wrong one.
		const meta = bundle(710_532);
		expect(modelTierCredit(meta, 'high').name).toBe('ESA');
		expect(modelTierCredit(meta, 'low').name).toBe('NASA');
		expect(modelTierCredit(bundle(0, false), 'low').name).toBe('ESA');
	});
});

describe('cheapTier', () => {
	it('is what a shape model takes: the same surface, decimated', () => {
		expect(cheapTier(bundle(1_593_000))).toBe('low');
		expect(cheapTier(bundle(1_593_000, false))).toBe('high');
	});
});
