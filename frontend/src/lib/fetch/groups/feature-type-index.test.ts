/**
 * The IAU code ↔ `ft-` slug table lives only in the export, served via
 * `groups/__index__.json`. Locks the lookup both ways.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const INDEX = {
	'ft-crater': { type: 'feature_type', applies_to: 'surface_feature', n: 5451, code: 'AA' },
	'ft-mons': { type: 'feature_type', applies_to: 'surface_feature', n: 308, code: 'MO' },
	'cat-moons': { type: 'category', applies_to: 'category', n: 987 }
};

beforeEach(async () => {
	// The loader memoizes its promise, so each case needs a fresh module.
	vi.resetModules();
	vi.stubGlobal(
		'fetch',
		vi.fn(async () => new Response(JSON.stringify(INDEX), { status: 200 }))
	);
});

async function registry() {
	return import('./registry');
}

describe('featureTypeCode', () => {
	it('resolves a slug to its IAU descriptor code', async () => {
		const { featureTypeCode } = await registry();
		expect(await featureTypeCode('ft-crater')).toBe('AA');
	});

	it('is undefined for a group that carries no code', async () => {
		const { featureTypeCode } = await registry();
		expect(await featureTypeCode('cat-moons')).toBeUndefined();
		expect(await featureTypeCode('ft-nonexistent')).toBeUndefined();
	});
});

describe('featureTypeSlug', () => {
	it('resolves an IAU code back to its slug', async () => {
		const { featureTypeSlug } = await registry();
		expect(await featureTypeSlug('MO')).toBe('ft-mons');
	});

	it('is undefined for a code no group claims', async () => {
		const { featureTypeSlug } = await registry();
		expect(await featureTypeSlug('ZZ')).toBeUndefined();
	});

	it('round-trips every ft- entry', async () => {
		const { featureTypeCode, featureTypeSlug } = await registry();
		for (const slug of ['ft-crater', 'ft-mons']) {
			const code = await featureTypeCode(slug);
			expect(await featureTypeSlug(code!)).toBe(slug);
		}
	});
});
