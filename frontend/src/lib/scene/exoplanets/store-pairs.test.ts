import { describe, expect, it, vi } from 'vitest';
import type { SystemNode } from '$lib/fetch/extrasolar/systems';
import { systemRow } from '$lib/fetch/extrasolar/__fixtures__/record';
import { SYSTEM_SLUG } from '$lib/fetch/extrasolar/lookup';
import { AU_SCALE } from '$lib/math/units';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { ExoplanetStore } from './store';
import { FRAME_OUTER_ORBITS } from './view';

/** The store frames a node of a star system by its drawn pair. */

const ROOT = 597894079;
const PAIR = 61023167;
const FIRST = 27468735;
const SECOND = 564339647;
const WIDE = 27424668;
const PLACES = new Map<number, [number, number, number]>([
	[FIRST, [100, 0, 0]],
	[SECOND, [300, 0, 0]]
]);

const nodes = vi.hoisted(() => ({ rows: [] as unknown[] }));

vi.mock('$lib/fetch/extrasolar/systems', async (original) => ({
	...(await original<typeof import('$lib/fetch/extrasolar/systems')>()),
	loadSystemNodes: async () => nodes.rows
}));
vi.mock('$lib/scene/setup/extrasolar', () => ({
	ensureExtrasolarBody: vi.fn(async () => ({ kind: 'missing' }))
}));

function body(id: number): PositionedBody {
	const row = id === ROOT || id === PAIR ? systemRow(FIRST) : undefined;
	const record = {
		id,
		metadata: { system: id === ROOT ? null : ROOT },
		rows: new Map(row ? [[SYSTEM_SLUG, row]] : [])
	};
	return {
		data: { id: `x-${id}`, objectType: ObjectType.EXTRASOLAR, parentId: '' },
		position: null,
		extrasolar: {
			id,
			record,
			scene: PLACES.get(id) ?? [900, 900, 900],
			tree: [0, 0, 0],
			colour: 1,
			teff: null
		}
	} as unknown as PositionedBody;
}

function setup(barycentre: number) {
	const member = (id: number, kind: string) => ({ id, kind, gMag: null, vMag: null, mass: null });
	const orbit = { a: 5, i: 30, om: 40, w: 0, period: 100, barycentre };
	nodes.rows = [
		{
			id: ROOT,
			depth: 0,
			primary: FIRST,
			orbit: null,
			tree: [],
			members: [member(PAIR, 'system'), member(WIDE, 'star')]
		},
		{
			id: PAIR,
			depth: 1,
			primary: FIRST,
			distance: 10,
			orbit,
			members: [member(FIRST, 'star'), member(SECOND, 'star')]
		}
	] as unknown as SystemNode[];
	const bodies = new Map([ROOT, PAIR, FIRST, SECOND, WIDE].map((id) => [`x-${id}`, body(id)]));
	const ctx = {
		getBody: (id: string) => bodies.get(id),
		bodies: { addExtrasolar: () => {} }
	} as unknown as ContextManager;
	return { store: new ExoplanetStore(ctx), bodies };
}

describe('the view of a node', () => {
	it('frames a pair by four of its orbits, at the barycentre', async () => {
		const { store, bodies } = setup(0.25);
		await store.ensureStarSystem(ROOT);
		expect(store.view(`x-${PAIR}`)?.distance).toBeCloseTo(FRAME_OUTER_ORBITS * 5 * AU_SCALE, 6);
		expect(bodies.get(`x-${PAIR}`)?.extrasolar?.scene).toEqual([100, 0, 0]);
	});

	it('frames a root by the pair of its primary, and sits there', async () => {
		const { store, bodies } = setup(0.25);
		await store.ensureStarSystem(ROOT);
		expect(store.view(`x-${ROOT}`)?.distance).toBeCloseTo(FRAME_OUTER_ORBITS * 5 * AU_SCALE, 6);
		expect(bodies.get(`x-${ROOT}`)?.extrasolar?.scene).toEqual(
			bodies.get(`x-${PAIR}`)?.extrasolar?.scene
		);
	});

	it('leaves a star to its own view', async () => {
		const { store } = setup(0.25);
		await store.ensureStarSystem(ROOT);
		expect(store.view(`x-${FIRST}`)).toBeNull();
		expect(store.view(`x-${WIDE}`)).toBeNull();
	});
});
