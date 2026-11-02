/**
 * On a bad line global.json can fail at boot, and a moon's spin then comes
 * without the angles its nutation terms pair with: Mimas's is 45° off in
 * 2026, and a spaceguesser round over Herschel was flown 45° west of it. The
 * scene keeps the sums, and joins them once the file comes in. Each test
 * loads the modules afresh, so global.json starts out not loaded.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { PositionedBody } from '$lib/types/objects';
import { isDrawn, type BodyObjects } from '$lib/scene/types';

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

type Apply = typeof import('./orientation-apply');
type SystemsGlobal = typeof import('$lib/fetch/systems-global');

let apply: Apply;
let systems: SystemsGlobal;

function context(bodies: PositionedBody[]): ContextManager {
	const byId = new Map(bodies.map((b) => [b.data.id, b]));
	return {
		getBody: (id: string) => byId.get(id),
		bodies: { dataVersion: 0, nutationAwaited: new Map() },
		credits: { registerOrientation: () => {} }
	} as unknown as ContextManager;
}

const bodyOf = (id: string) => ({ data: { id } }) as PositionedBody;

async function globalJsonLoads() {
	vi.stubGlobal('fetch', async () => Response.json({ nut_prec_angles: { 6: SATURN_ANGLES } }));
	await systems.loadSystemsGlobal();
}

async function globalJsonIsNotThere() {
	vi.stubGlobal('fetch', async () => new Response(null, { status: 404 }));
	await systems.loadSystemsGlobal().catch(() => {});
}

beforeEach(async () => {
	vi.resetModules();
	apply = await import('./orientation-apply');
	systems = await import('$lib/fetch/systems-global');
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('joinAwaitedNutation', () => {
	it('joins the terms of a spin that came before global.json, and places the body again', async () => {
		const mimas = bodyOf('naif-601');
		const ctx = context([mimas]);
		apply.applyBodyOrientation(mimas, MIMAS_SPIN, MIMAS_SUMS, ctx);
		expect(mimas.nutPrec).toBeUndefined();
		expect(ctx.bodies.nutationAwaited.get('naif-601')).toBe(mimas);
		expect(mimas.nutPrecAwaited).toEqual(MIMAS_SUMS);

		await globalJsonLoads();
		const placed = ctx.bodies.dataVersion;
		expect(apply.joinAwaitedNutation(ctx)).toEqual([mimas]);
		expect(mimas.nutPrec).toEqual({ ...MIMAS_SUMS, angles: SATURN_ANGLES, phaseDegree: 1 });
		expect(mimas.nutPrecAwaited).toBeUndefined();
		expect(ctx.bodies.nutationAwaited.size).toBe(0);
		expect(ctx.bodies.dataVersion).toBe(placed + 1);
	});

	it('does not draw the body till its terms are joined', async () => {
		const mimas = { ...bodyOf('naif-601'), position: [0, 0, 0] } as PositionedBody;
		const bo = { body: mimas } as BodyObjects;
		const ctx = context([mimas]);
		expect(isDrawn(bo)).toBe(true);
		apply.applyBodyOrientation(mimas, MIMAS_SPIN, MIMAS_SUMS, ctx);
		expect(isDrawn(bo)).toBe(false);
		await globalJsonLoads();
		apply.joinAwaitedNutation(ctx);
		expect(isDrawn(bo)).toBe(true);
	});

	it('joins the body it was given, which the scene may hold under no id', async () => {
		const mimas = bodyOf('naif-601');
		const ctx = context([]);
		apply.applyBodyOrientation(mimas, MIMAS_SPIN, MIMAS_SUMS, ctx);
		await globalJsonLoads();
		expect(apply.joinAwaitedNutation(ctx)).toEqual([mimas]);
		expect(mimas.nutPrec).toBeDefined();
	});

	it('lets the spin go on without its terms where the data host has no global.json', async () => {
		const mimas = bodyOf('naif-601');
		const ctx = context([mimas]);
		apply.applyBodyOrientation(mimas, MIMAS_SPIN, MIMAS_SUMS, ctx);
		await globalJsonIsNotThere();
		expect(apply.joinAwaitedNutation(ctx)).toEqual([]);
		expect(mimas.nutPrec).toBeUndefined();
		// The body is drawn, and the measures answer again, as before the wait.
		expect(mimas.nutPrecAwaited).toBeUndefined();
		expect(ctx.bodies.nutationAwaited.size).toBe(0);
	});

	it('keeps no terms for a spin given again without them', async () => {
		const mimas = bodyOf('naif-601');
		const ctx = context([mimas]);
		apply.applyBodyOrientation(mimas, MIMAS_SPIN, MIMAS_SUMS, ctx);
		apply.applyBodyOrientation(mimas, MIMAS_SPIN, undefined, ctx);
		expect(ctx.bodies.nutationAwaited.size).toBe(0);

		await globalJsonLoads();
		expect(apply.joinAwaitedNutation(ctx)).toEqual([]);
		expect(mimas.nutPrec).toBeUndefined();
	});

	it('keeps nothing once global.json has loaded', async () => {
		await globalJsonLoads();
		const mimas = bodyOf('naif-601');
		const ctx = context([mimas]);
		apply.applyBodyOrientation(mimas, MIMAS_SPIN, MIMAS_SUMS, ctx);
		expect(mimas.nutPrec).toBeDefined();
		expect(ctx.bodies.nutationAwaited.size).toBe(0);
	});
});
