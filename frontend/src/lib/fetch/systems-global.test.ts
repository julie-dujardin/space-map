import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadSystemsGlobal, nutPrecFor } from './systems-global';

const SUMS = { ra: [1], dec: [2], pm: [3] };

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('loadSystemsGlobal', () => {
	it('fetches again after an error status', async () => {
		const answers = [
			new Response(null, { status: 503 }),
			Response.json({ nut_prec_angles: { 6: [316.45, 506.2] } })
		];
		vi.stubGlobal('fetch', async () => answers.shift());
		await expect(loadSystemsGlobal()).rejects.toThrow('503');
		expect(nutPrecFor('naif-601', SUMS)).toBeUndefined();
		await loadSystemsGlobal();
		expect(nutPrecFor('naif-601', SUMS)).toEqual({
			...SUMS,
			angles: [316.45, 506.2],
			phaseDegree: 1
		});
	});
});
