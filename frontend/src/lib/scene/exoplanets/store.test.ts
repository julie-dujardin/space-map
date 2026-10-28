import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
	PlanetCatalogue,
	type PlanetIndexFile,
	type PlanetSystem
} from '$lib/fetch/extrasolar/planets';
import type { ExtrasolarMetadata } from '$lib/fetch/extrasolar/files';
import { extrasolarObjectId } from '$lib/fetch/extrasolar/ids';
import { sphericalToCartesian } from '$lib/math/spherical';
import { AU_SCALE } from '$lib/math/units';
import type { PromotionRegistry } from '$lib/scene/focus/promotion';
import { ensureExtrasolarBody } from '$lib/scene/setup/extrasolar';
import { treeToScene } from '$lib/scene/starfield/tree';
import { BodyIndex } from '$lib/scene/state/bodies.svelte';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { ExoplanetStore } from './store';
import { ExoplanetSystems } from './systems';
import { FRAME_ELEVATION_DEG, frameDirection, orbitNormal } from './view';
import { ALPHA_CEN, INDEX, MERGED_HOST, elements, host, planet } from './__fixtures__/system';

/** The store holds the bodies of the systems in use, and frames them. */

const PROXIMA = 27424668;
const TOLIMAN = 564339647;
const PLACE: [number, number, number] = [-2e6, 1e6, -2.4e6];
/** A resolved star system: its record gives it no place. */
const PAIR = 3 * 2 ** 24 + 5;
/** A star of the pair, with planets of its own. */
const PAIR_A = 2 ** 24 + 9;
const PAIR_PLACE: [number, number, number] = [10, -20, 30];

vi.mock('$lib/scene/setup/extrasolar', () => ({
	// A star body at a fixed place, as the record lookup makes it.
	ensureExtrasolarBody: vi.fn(async (ctx: ContextManager, objectId: string) => {
		const id = Number(objectId.slice(2));
		const place = id === PAIR ? null : PLACE;
		const body = {
			data: { id: objectId, objectType: ObjectType.EXTRASOLAR, parentId: '' },
			position: null,
			extrasolar: { id, scene: place, tree: place }
		} as unknown as PositionedBody;
		ctx.bodies.addExtrasolar(body);
		return { kind: 'live' };
	})
}));

function setup(files: Record<string, { token: string }>) {
	const reads: string[] = [];
	const catalogue = new PlanetCatalogue({
		metadata: async () =>
			({
				planets: {
					token: '0000000000000000',
					index: 'planets/index.json.gz',
					system: 'planets/{key}.json.gz'
				}
			}) as ExtrasolarMetadata,
		json: async <T extends { token: string }>(path: string): Promise<T> => {
			reads.push(path);
			if (!files[path]) throw new Error(`${path} returned 404`);
			return files[path] as T;
		},
		allowed: () => true
	});
	const bodies = new BodyIndex();
	const ctx = {
		bodies,
		getBody: (id: string) => bodies.getBody(id),
		visibility: {}
	} as unknown as ContextManager;
	const store = new ExoplanetStore(ctx, catalogue);
	(ctx as { exoplanets: ExoplanetStore }).exoplanets = store;
	return { store, bodies, reads, ctx };
}

const FILES = { 'planets/index.json.gz': INDEX, 'planets/27424668.json.gz': ALPHA_CEN };

/** A resolved pair with a circumbinary planet, keyed by the pair, and a star
 *  of the pair with a planet. The index places the pair at its primary. */
const PAIR_INDEX: PlanetIndexFile = {
	token: '0000000000000000',
	hosts: [
		{ id: PAIR_A, system: PAIR, planets: [1], position: [1, 2, 3], outer_orbit: 1 },
		{ id: PAIR, system: PAIR, planets: [1], position: PAIR_PLACE, outer_orbit: 1 }
	],
	aliases: {}
};
const PAIR_SYSTEM: PlanetSystem = {
	token: '0000000000000000',
	system: PAIR,
	hosts: [host(PAIR, [1]), host(PAIR_A, [1])],
	planets: [planet(PAIR, 1, elements(1)), planet(PAIR_A, 1, elements(0.5))]
};
const PAIR_FILES = {
	'planets/index.json.gz': PAIR_INDEX,
	[`planets/${PAIR}.json.gz`]: PAIR_SYSTEM
};

function sceneOf(tree: [number, number, number]): [number, number, number] {
	const at = treeToScene(...tree, { x: 0, y: 0, z: 0 });
	return [at.x, at.y, at.z];
}

describe('ExoplanetStore', () => {
	beforeEach(() => vi.clearAllMocks());

	it('holds a host system: every planet of the file, and the star', async () => {
		const { store, bodies, reads } = setup(FILES);
		expect(store.held(TOLIMAN)).toBeNull();
		const held = await store.ensureHost(TOLIMAN);
		expect(held?.file.system).toBe(PROXIMA);
		expect(store.held(PROXIMA)).toBe(held);
		expect(held?.planets.get(PROXIMA)?.map((b) => b.data.id)).toEqual([
			'x-27424668-b-1',
			'x-27424668-b-2'
		]);
		expect(bodies.getBody('x-564339647-b-1')?.exoplanet?.host).toBe(TOLIMAN);
		expect(bodies.getBody(extrasolarObjectId(TOLIMAN))?.extrasolar).toBeDefined();
		await store.ensureHost(PROXIMA);
		expect(reads).toEqual(['planets/index.json.gz', 'planets/27424668.json.gz']);
	});

	it('reads the index once, and again after a load that failed', async () => {
		const files: Record<string, { token: string }> = {};
		const { store, reads } = setup(files);
		await expect(store.loadIndex()).rejects.toThrow();
		expect(store.index).toBeNull();
		files['planets/index.json.gz'] = INDEX;
		await Promise.all([store.loadIndex(), store.loadIndex()]);
		await store.loadIndex();
		expect(store.index?.host(PROXIMA)).toBeDefined();
		expect(reads).toEqual(['planets/index.json.gz', 'planets/index.json.gz']);
	});

	it('holds nothing for a star with no planets, or a planet with no page', async () => {
		const { store, reads } = setup(FILES);
		expect(await store.ensureHost(22137869)).toBeNull();
		await store.ensurePlanet('x-27424668-b-9');
		await store.ensurePlanet('naif-399');
		expect(reads).toEqual(['planets/index.json.gz']);
		await store.ensurePlanet('x-27424668-b-2');
		expect(store.held(PROXIMA)).not.toBeNull();
	});

	it('holds the system of the planet an alias leads to, on another host', async () => {
		const { store, reads } = setup(FILES);
		await store.ensurePlanet(`x-${MERGED_HOST}-b-1`);
		expect(store.held(PROXIMA)).not.toBeNull();
		expect(store.held(MERGED_HOST)).toBeNull();
		expect(reads).toEqual(['planets/index.json.gz', 'planets/27424668.json.gz']);
	});

	it('lands a link to an alias on the live planet', async () => {
		const { store, bodies } = setup(FILES);
		const alias = `x-${MERGED_HOST}-b-1`;
		await store.ensurePlanet(alias);
		// goTo and the focus find the target by the ID of the link.
		const body = bodies.getBody(alias);
		expect(body?.data.id).toBe('x-27424668-b-2');
		expect(body).toBe(bodies.getBody('x-27424668-b-2'));
		expect(store.view(body!.data.id)).not.toBeNull();
	});

	it('frames a star from over its outer plane, and a planet from over its own', async () => {
		const { store } = setup(FILES);
		expect(store.view('x-27424668')).toBeNull();
		await store.ensureHost(PROXIMA);
		const look = (objectId: string) => {
			const view = store.view(objectId)!;
			return { view, at: sphericalToCartesian([0, 0, 0], view.latitude, view.longitude, 1) };
		};
		const star = look('x-27424668');
		expect(star.view.distance).toBeCloseTo(4 * 1.5 * AU_SCALE, 9);
		const outer = frameDirection(PLACE, orbitNormal(100, 200), FRAME_ELEVATION_DEG);
		for (let k = 0; k < 3; k++) expect(star.at[k]).toBeCloseTo(outer[k], 9);
		const b = look('x-27424668-b-1');
		expect(b.view.distance).toBeCloseTo(star.view.distance, 9);
		const own = frameDirection(PLACE, orbitNormal(30, 40), FRAME_ELEVATION_DEG);
		for (let k = 0; k < 3; k++) expect(b.at[k]).toBeCloseTo(own[k], 9);
		// Toliman's only planet has no orbit: the stand-in span, over the ecliptic.
		await store.ensureHost(TOLIMAN);
		const toliman = look('x-564339647');
		expect(toliman.view.distance).toBeCloseTo(4 * AU_SCALE, 9);
		const flat = frameDirection(PLACE, [0, 1, 0], FRAME_ELEVATION_DEG);
		for (let k = 0; k < 3; k++) expect(toliman.at[k]).toBeCloseTo(flat[k], 9);
	});

	it('places a host with no place of its own where the index puts it', async () => {
		const { store, bodies } = setup(PAIR_FILES);
		await store.ensureHost(PAIR);
		const star = bodies.getBody(extrasolarObjectId(PAIR))?.extrasolar;
		expect(star?.scene).toEqual(sceneOf(PAIR_PLACE));
		// No tree place: the starfield does not draw it as a star.
		expect(star?.tree).toBeNull();
		expect(store.view(extrasolarObjectId(PAIR))).not.toBeNull();
		// A host with a place of its own keeps it.
		await store.ensureHost(PAIR_A);
		expect(bodies.getBody(extrasolarObjectId(PAIR_A))?.extrasolar?.scene).toEqual(PLACE);
	});

	it('places a host whose body came before its system was held', async () => {
		const { store, bodies, ctx } = setup(PAIR_FILES);
		await store.ensureHost(PAIR_A);
		// A lookup of the pair alone, as a link to its page makes it.
		await ensureExtrasolarBody(ctx, extrasolarObjectId(PAIR));
		const body = bodies.getBody(extrasolarObjectId(PAIR))!;
		expect(body.extrasolar?.scene).toBeNull();
		const promotion = { syncSystemBodies: vi.fn() } as unknown as PromotionRegistry;
		const systems = new ExoplanetSystems(ctx, promotion, () => {});
		const frame = { camera: [0, 0, 0] as const, viewportPx: 1000, fovDeg: 60, dtMs: 16 };
		systems.update({ ...frame, outside: 1, focused: body });
		await vi.waitFor(() =>
			expect(bodies.getBody(extrasolarObjectId(PAIR))?.extrasolar?.scene).toEqual(
				sceneOf(PAIR_PLACE)
			)
		);
	});

	it('drops the bodies of the oldest systems past a few, but not those in use', async () => {
		const ids = Array.from({ length: 20 }, (_, k) => 2 ** 24 + 100 + k);
		const index: PlanetIndexFile = {
			token: '0000000000000000',
			hosts: ids.map((id) => ({
				id,
				system: id,
				planets: [1],
				position: [1, 1, 1],
				outer_orbit: 1
			})),
			aliases: {}
		};
		const files: Record<string, { token: string }> = { 'planets/index.json.gz': index };
		for (const id of ids) {
			const file: PlanetSystem = {
				token: '0000000000000000',
				system: id,
				hosts: [host(id, [1])],
				planets: [planet(id, 1, elements(1))]
			};
			files[`planets/${id}.json.gz`] = file;
		}
		const { store, bodies } = setup(files);
		await store.ensureHost(ids[0]);
		store.use(new Set([ids[0]]));
		for (const id of ids.slice(1)) await store.ensureHost(id);
		expect(store.held(ids[0])).not.toBeNull();
		expect(bodies.getBody(`x-${ids[0]}-b-1`)).toBeDefined();
		expect(store.held(ids[1])).toBeNull();
		expect(bodies.getBody(`x-${ids[1]}-b-1`)).toBeUndefined();
		expect(store.held(ids[19])).not.toBeNull();
	});
});
