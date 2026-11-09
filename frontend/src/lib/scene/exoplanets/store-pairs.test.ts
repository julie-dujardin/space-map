import { afterEach, describe, expect, it, vi } from 'vitest';
import type { SystemNode } from '$lib/fetch/extrasolar/systems';
import { systemRow } from '$lib/fetch/extrasolar/__fixtures__/record';
import { SYSTEM_SLUG } from '$lib/fetch/extrasolar/lookup';
import { AU_SCALE } from '$lib/math/units';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { PlanetCatalogue, type PlanetSystem } from '$lib/fetch/extrasolar/planets';
import type { ExtrasolarMetadata } from '$lib/fetch/extrasolar/files';
import type { ExtrasolarLookupResult } from '$lib/fetch/extrasolar/lookup';
import { ensureExtrasolarBody } from '$lib/scene/setup/extrasolar';
import { ExoplanetStore } from './store';
import { FRAME_OUTER_ORBITS } from './view';
import { elements, host, planet } from './__fixtures__/system';

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

const nodes = vi.hoisted(() => ({ rows: [] as unknown[], loads: 0 }));

vi.mock('$lib/fetch/extrasolar/systems', async (original) => ({
	...(await original<typeof import('$lib/fetch/extrasolar/systems')>()),
	loadSystemNodes: async () => {
		nodes.loads++;
		return nodes.rows;
	}
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
	const orbit = { first: 0, second: 1, a: 5, i: 30, om: 40, w: 0, period: 100, barycentre };
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
		expect(bodies.get(`x-${PAIR}`)?.extrasolar?.scene).toEqual([150, 0, 0]);
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

describe('the view of a point that a held host took over', () => {
	afterEach(() => vi.mocked(ensureExtrasolarBody).mockReset());

	const POINT = 23025959;
	const HOST = 593451303;
	const OTHER = 593451304;
	const AT: [number, number, number] = [100, 0, 0];
	const TOKEN = '0000000000000000';

	/** With `ownPlanet`, the point keeps a planet of its own, on a wider orbit. */
	function setupPoint(ownPlanet = false) {
		const member = (id: number) => ({ id, kind: 'held star', gMag: null, vMag: null, mass: null });
		nodes.rows = [
			{
				id: POINT,
				point: true,
				depth: 0,
				primary: POINT,
				orbit: null,
				tree: [],
				members: [member(HOST), member(OTHER)]
			},
			{ id: HOST, depth: 1, parent: POINT, orbit: null, members: [], star: { teff: 6300 } },
			{ id: OTHER, depth: 1, parent: POINT, orbit: null, members: [], star: { teff: null } }
		] as unknown as SystemNode[];
		const star = (id: number, at: [number, number, number] | null) => {
			const b = body(id);
			b.extrasolar!.scene = at;
			b.extrasolar!.tree = at;
			b.extrasolar!.record = {
				id,
				metadata: { system: id === POINT ? null : POINT },
				rows: new Map(id === POINT ? [[SYSTEM_SLUG, systemRow(POINT)]] : [])
			} as never;
			return b;
		};
		const bodies = new Map(
			[POINT, HOST, OTHER].map((id) => [`x-${id}`, star(id, id === POINT ? AT : null)])
		);
		const own = ownPlanet ? [POINT] : [];
		const files: Record<string, unknown> = {
			'planets/index.json.gz': {
				token: TOKEN,
				hosts: [...own, HOST].map((id) => ({
					id,
					system: POINT,
					planets: [1],
					position: null,
					outer_orbit: id === HOST ? 0.5 : 2
				})),
				aliases: {}
			},
			[`planets/${POINT}.json.gz`]: {
				token: TOKEN,
				system: POINT,
				hosts: [...own, HOST].map((id) => host(id, [1])),
				planets: [
					...own.map((id) => planet(id, 1, elements(2, { i: 70 }))),
					planet(HOST, 1, elements(0.5))
				]
			} satisfies PlanetSystem
		};
		const catalogue = new PlanetCatalogue({
			metadata: async () =>
				({
					planets: { token: TOKEN, index: 'planets/index.json.gz', system: 'planets/{key}.json.gz' }
				}) as ExtrasolarMetadata,
			json: async <T>(path: string) => files[path] as T,
			allowed: () => true
		});
		const ctx = {
			getBody: (id: string) => bodies.get(id),
			bodies: { addExtrasolar: () => {}, addExoplanets: () => {} }
		} as unknown as ContextManager;
		return { store: new ExoplanetStore(ctx, catalogue), bodies };
	}

	it('frames the planets of the host, at the point', async () => {
		const { store, bodies } = setupPoint();
		const found = { kind: 'live', record: bodies.get(`x-${POINT}`)!.extrasolar!.record };
		await store.ensureStarSystemOf(found as ExtrasolarLookupResult);
		const view = store.view(`x-${POINT}`);
		expect(view).not.toBeNull();
		expect(view).toEqual(store.view(`x-${HOST}`));
		expect(bodies.get(`x-${HOST}`)?.extrasolar?.scene).toEqual(AT);
	});

	it('frames the planets of the point where it has its own', async () => {
		const { store, bodies } = setupPoint(true);
		const found = { kind: 'live', record: bodies.get(`x-${POINT}`)!.extrasolar!.record };
		await store.ensureStarSystemOf(found as ExtrasolarLookupResult);
		expect(store.heldHostOf(POINT)).toBe(HOST);
		expect(store.view(`x-${POINT}`)).not.toEqual(store.view(`x-${HOST}`));
		expect(store.planeNormal(`x-${POINT}`)).toEqual(store.planeNormal(`x-${POINT}-b-1`));
	});

	it('loads the system once for a link to the point', async () => {
		const { store, bodies } = setupPoint();
		vi.mocked(ensureExtrasolarBody).mockImplementation(async (_ctx, id) => ({
			kind: 'live',
			record: bodies.get(id)!.extrasolar!.record
		}));
		nodes.loads = 0;
		const found = { kind: 'live', record: bodies.get(`x-${POINT}`)!.extrasolar!.record };
		await store.ensureStarSystemOf(found as ExtrasolarLookupResult);
		expect(nodes.loads).toBe(1);
		expect(store.held(HOST)).not.toBeNull();
	});
});
