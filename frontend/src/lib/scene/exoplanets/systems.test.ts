import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SYSTEM_SLUG, type ExtrasolarRecord, type TableRow } from '$lib/fetch/extrasolar/lookup';
import { systemRow } from '$lib/fetch/extrasolar/__fixtures__/record';
import type { PromotionRegistry } from '$lib/scene/focus/promotion';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { ObjectType, type PositionedBody, type StarAnchor } from '$lib/types/objects';
import { ExoplanetSystems, EXACT_STARS, type SystemsFrame } from './systems';

const load = vi.hoisted(() => ({
	points: vi.fn<(root: number) => Promise<number[]>>(),
	body: vi.fn<(ctx: unknown, id: string) => Promise<unknown>>()
}));

/** A star system with no drawn pair, as the store holds it. */
async function planOf(root: number) {
	const points = await load.points(root);
	await Promise.all(points.map((id) => load.body(null, `x-${id}`)));
	return { root, nodes: new Map(), points, pairs: [], heldHosts: new Map(), ids: points };
}

function star(id: number, root: number | null = null, row?: TableRow): PositionedBody {
	const metadata = { system: root };
	const record = {
		id,
		metadata,
		rows: new Map(row ? [[SYSTEM_SLUG, row]] : [])
	} as unknown as ExtrasolarRecord;
	const anchor = {
		id,
		record,
		scene: [id, 0, 0],
		tree: [id, 0, 0],
		point: id
	} as unknown as StarAnchor;
	return {
		data: { id: `x-${id}`, objectType: ObjectType.EXTRASOLAR, parentId: '' },
		position: null,
		extrasolar: anchor
	} as unknown as PositionedBody;
}

/** A resolved node or held star: a place, a System row, and no tree place. */
function node(id: number, root: number, primary: number | null, parent?: number): PositionedBody {
	const row = systemRow(primary);
	if (parent !== undefined) {
		vi.spyOn(row, 'number').mockImplementation((name) => (name === 'parent' ? parent : null));
	}
	const body = star(id, root, row);
	body.extrasolar!.tree = null;
	body.extrasolar!.point = parent ?? primary ?? id;
	return body;
}

function planetOf(host: PositionedBody): PositionedBody {
	return {
		data: { id: `${host.data.id}-b-1`, objectType: ObjectType.EXOPLANET, parentId: host.data.id },
		position: null
	} as unknown as PositionedBody;
}

/** Systems over a scene that holds `bodies`, as they are at each lookup. */
function systemsWith(bodies: PositionedBody[], pins?: (ids: ReadonlySet<string>) => void) {
	const ctx = {
		getBody: (id: string) => bodies.find((body) => body.data.id === id),
		place: (body: PositionedBody) => body.position,
		exoplanets: {
			index: null,
			loadIndex: async () => {},
			ensureStarSystem: planOf,
			heldHostOf: () => undefined
		},
		bodies: { pinExtrasolar: pins ?? (() => {}) },
		visibility: {}
	} as unknown as ContextManager;
	const promotion = { syncSystemBodies: () => {} } as unknown as PromotionRegistry;
	return new ExoplanetSystems(ctx, promotion, () => {});
}

const frame = (focused: PositionedBody | undefined, camera = [0, 0, 0]): SystemsFrame =>
	({ focused, camera }) as unknown as SystemsFrame;

/** Let the loads of a frame land. */
const landed = () => new Promise((resolve) => setTimeout(resolve));

/** The IDs that the renderer hands the starfield. */
function exactIds(systems: ExoplanetSystems, focused: PositionedBody | undefined): number[] {
	const stars = systems.exactStars(focused);
	return [...stars, ...systems.companions(stars)].map((anchor) => anchor.id);
}

describe('ExoplanetSystems.exactStars', () => {
	it('draws the stars of a trip exactly, after the focused one', () => {
		const sirius = star(1);
		const proxima = star(2);
		const proximaB = planetOf(proxima);
		const tauCeti = star(3);
		const systems = systemsWith([sirius, proxima, proximaB, tauCeti]);
		const ids = systems
			.exactStars(sirius, [proximaB.data.id, tauCeti.data.id, 'x-404'])
			.map((anchor) => anchor.id);
		expect(ids).toEqual([1, 2, 3]);
	});

	it('names a star once, and the solar system not at all', () => {
		const proxima = star(2);
		const earth = {
			data: { id: 'naif-399', objectType: ObjectType.PLANET, parentId: 'naif-3' },
			position: null
		} as unknown as PositionedBody;
		const systems = systemsWith([proxima, earth]);
		const ids = systems.exactStars(proxima, [earth.data.id, proxima.data.id]);
		expect(ids.map((anchor) => anchor.id)).toEqual([2]);
	});

	it('draws the star of an end that streams in after the trip is drawn', () => {
		const scene: PositionedBody[] = [];
		const systems = systemsWith(scene);
		const proxima = star(2);
		expect(systems.exactStars(undefined, [proxima.data.id])).toEqual([]);
		scene.push(proxima);
		expect(systems.exactStars(undefined, [proxima.data.id]).map((anchor) => anchor.id)).toEqual([
			2
		]);
	});
});

describe('the focused star system', () => {
	const ROOT = 100;
	beforeEach(() => {
		load.points.mockReset();
		load.body.mockReset();
		load.body.mockResolvedValue(undefined);
	});

	it('draws the focused star first, then its system by camera distance', async () => {
		const stars = [star(5, ROOT), star(6, ROOT), star(7, ROOT)];
		load.points.mockResolvedValue([5, 6, 7]);
		const systems = systemsWith(stars);
		systems.update(frame(stars[1], [7, 0, 0]));
		expect(load.points).toHaveBeenCalledWith(ROOT);
		await landed();
		systems.update(frame(stars[1], [7, 0, 0]));
		expect(exactIds(systems, stars[1])).toEqual([6, 7, 5]);
		systems.update(frame(stars[1], [0, 0, 0]));
		expect(exactIds(systems, stars[1])).toEqual([6, 5, 7]);
	});

	it('holds the bodies of the system, and lets them go with the focus', async () => {
		const stars = [star(5, ROOT), star(6, ROOT)];
		load.points.mockResolvedValue([5, 6]);
		const pins: string[][] = [];
		const systems = systemsWith(stars, (ids) => pins.push([...ids]));
		systems.update(frame(stars[0]));
		await landed();
		expect(load.body.mock.calls.map(([, id]) => id)).toEqual(['x-5', 'x-6']);
		systems.update(frame(stars[0]));
		expect(pins.at(-1)).toEqual(['x-5', 'x-6']);
		systems.update(frame(undefined));
		expect(pins.at(-1)).toEqual([]);
		expect(systems.exactStars(undefined)).toEqual([]);
	});

	it('leaves the slots of the ends and the focused star to them', async () => {
		const stars = Array.from({ length: EXACT_STARS + 1 }, (_, i) => star(i + 1, ROOT));
		const end = star(90);
		load.points.mockResolvedValue(stars.map((body) => body.extrasolar!.id));
		const systems = systemsWith([...stars, end]);
		systems.update(frame(stars[0]));
		await landed();
		systems.update(frame(stars[0]));
		const exact = systems.exactStars(stars[0], [end.data.id]);
		expect(exact.map((anchor) => anchor.id)).toEqual([1, 90]);
		const companions = systems.companions(exact).map((anchor) => anchor.id);
		expect(companions).toHaveLength(EXACT_STARS - 2);
		expect(companions).not.toContain(1);
	});

	it('draws the primary for a resolved node, and never the node', async () => {
		const stars = [star(5, ROOT), star(6, ROOT)];
		const root = node(ROOT, ROOT, 5);
		root.extrasolar!.record.metadata.system = null;
		load.points.mockResolvedValue([6, 5]);
		const systems = systemsWith([root, ...stars]);
		systems.update(frame(root, [6, 0, 0]));
		expect(exactIds(systems, root)).toEqual([5]);
		await landed();
		systems.update(frame(root, [6, 0, 0]));
		expect(exactIds(systems, root)).toEqual([5, 6]);
	});

	it('draws the point of a focused held star', async () => {
		const point = star(5, ROOT);
		const held = node(50, ROOT, null, 5);
		const systems = systemsWith([point, held]);
		load.points.mockResolvedValue([5]);
		systems.update(frame(held));
		await landed();
		systems.update(frame(held));
		expect(exactIds(systems, held)).toEqual([5]);
	});

	it('climbs from a held star through a resolved node to its primary', async () => {
		const point = star(5, ROOT);
		const pair = node(40, ROOT, 5);
		const held = node(50, ROOT, null, 40);
		const systems = systemsWith([point, pair, held]);
		expect(systems.exactStars(held).map((anchor) => anchor.id)).toEqual([5]);
	});

	it('follows a planet to the system of its host', async () => {
		const host = star(5, ROOT);
		const other = star(6, ROOT);
		const planet = planetOf(host);
		planet.exoplanet = { host: 5 } as PositionedBody['exoplanet'];
		load.points.mockResolvedValue([5, 6]);
		const systems = systemsWith([host, other, planet]);
		systems.update(frame(planet));
		await landed();
		systems.update(frame(planet));
		expect(exactIds(systems, planet)).toEqual([5, 6]);
	});

	it('stops at the limit, and asks nothing for a star in no system', async () => {
		const stars = Array.from({ length: EXACT_STARS + 2 }, (_, i) => star(i + 1, ROOT));
		load.points.mockResolvedValue(stars.map((body) => body.extrasolar!.id));
		const systems = systemsWith(stars);
		systems.update(frame(stars[0]));
		await landed();
		systems.update(frame(stars[0]));
		expect(exactIds(systems, stars[0])).toHaveLength(EXACT_STARS);

		const alone = star(50);
		systems.update(frame(alone));
		expect(load.points).toHaveBeenCalledTimes(1);
		expect(systems.exactStars(alone).map((anchor) => anchor.id)).toEqual([50]);
	});

	it('asks for a failed system again after a wait', async () => {
		vi.useFakeTimers();
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		const stars = [star(5, ROOT), star(6, ROOT)];
		load.points.mockRejectedValueOnce(new Error('503')).mockResolvedValue([5, 6]);
		const systems = systemsWith(stars);
		systems.update(frame(stars[0]));
		await vi.advanceTimersByTimeAsync(0);
		systems.update(frame(stars[0]));
		expect(load.points).toHaveBeenCalledTimes(1);
		await vi.advanceTimersByTimeAsync(10_000);
		systems.update(frame(stars[0]));
		expect(load.points).toHaveBeenCalledTimes(2);
		warn.mockRestore();
		vi.useRealTimers();
	});
});
