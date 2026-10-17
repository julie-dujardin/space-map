import { beforeAll, describe, expect, it, vi } from 'vitest';
import { loadSystemsGlobal } from '$lib/fetch/systems-global';
import type { PositionedBody } from '$lib/types/objects';
import { applyBodyOrientation } from './orientation-apply';

const MIMAS_SPIN = {
	pole_ra_0: 40.66,
	pole_ra_1: -0.036,
	pole_dec_0: 83.52,
	pole_dec_1: -0.004,
	w0: 333.46,
	w1: 381.994555,
	w2: 0
};
const MIMAS_SUMS = { ra: [0, 0, 13.56], dec: [0, 0, -1.53], pm: [0, 0, -13.48, 0, -44.85] };
const SATURN_ANGLES = [
	353.32, 75706.7, 28.72, 75706.7, 177.4, -36505.5, 300.0, -7225.9, 316.45, 506.2
];

beforeAll(async () => {
	vi.stubGlobal('fetch', async () => Response.json({ nut_prec_angles: { 6: SATURN_ANGLES } }));
	await loadSystemsGlobal();
	vi.unstubAllGlobals();
});

const bodyOf = (id: string) => ({ data: { id } }) as PositionedBody;

describe('applyBodyOrientation', () => {
	// Mimas's object bundle can land before the Saturn system file: a spin
	// adopted from it without the terms is 45° off in 2026.
	it('joins the nutation terms with the angles of the system', () => {
		const mimas = bodyOf('naif-601');
		applyBodyOrientation(mimas, MIMAS_SPIN, MIMAS_SUMS);
		expect(mimas.nutPrec).toEqual({ ...MIMAS_SUMS, angles: SATURN_ANGLES, phaseDegree: 1 });
	});

	it('keeps no terms from a spin it replaces', () => {
		const mimas = bodyOf('naif-601');
		applyBodyOrientation(mimas, MIMAS_SPIN, MIMAS_SUMS);
		applyBodyOrientation(mimas, MIMAS_SPIN, undefined);
		expect(mimas.nutPrec).toBeUndefined();
	});
});
