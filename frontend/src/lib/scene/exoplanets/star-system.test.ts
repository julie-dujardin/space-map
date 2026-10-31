import { describe, expect, it, vi } from 'vitest';
import type { HeldStarValues, PairOrbit, SystemNode } from '$lib/fetch/extrasolar/systems';
import { SYSTEM_SLUG, type ExtrasolarRecord } from '$lib/fetch/extrasolar/lookup';
import { systemRow } from '$lib/fetch/extrasolar/__fixtures__/record';
import { SOLAR_RADIUS_KM } from '$lib/math/units';
import type { PromotionRegistry } from '$lib/scene/focus/promotion';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { drawnPairs } from './pair-orbits';
import {
	FocusedStarSystem,
	holdStarSystem,
	loadStarSystem,
	type StarSystemPlan
} from './star-system';
import { ExoplanetSystems, type SystemsFrame } from './systems';

vi.mock('$lib/scene/setup/extrasolar', () => ({
	ensureExtrasolarBody: vi.fn(async () => ({ kind: 'missing' }))
}));

const rows = vi.hoisted(() => ({ nodes: [] as unknown[] }));
vi.mock('$lib/fetch/extrasolar/systems', async (original) => ({
	...(await original<typeof import('$lib/fetch/extrasolar/systems')>()),
	loadSystemNodes: vi.fn(async () => rows.nodes)
}));

const ROOT = 1;
const POINT = 1;
const HELD_A = 11;
const HELD_B = 12;

function body(id: number, scene: [number, number, number] | null, root = ROOT): PositionedBody {
	const record = {
		id,
		home: 'point-source',
		metadata: { system: id === root ? null : root },
		rows: new Map(id === root ? [[SYSTEM_SLUG, systemRow(id)]] : [])
	} as unknown as ExtrasolarRecord;
	return {
		data: { id: `x-${id}`, objectType: ObjectType.EXTRASOLAR, parentId: '', radiusKm: NaN },
		position: scene,
		extrasolar: {
			id,
			record,
			scene,
			tree: scene,
			absMag: 5,
			colour: 1,
			radiusKm: null,
			teff: null
		}
	} as unknown as PositionedBody;
}

function orbit(fields: Partial<PairOrbit> = {}): PairOrbit {
	const elements = { a: 2, e: 0, i: 0, om: 0, w: 0, ma: 0, n: 1, epoch: 0 };
	return { ...elements, period: 360, barycentre: 0.25, ...fields } as PairOrbit;
}

function held(id: number, values: Partial<HeldStarValues> = {}): SystemNode {
	const star = { mass: 1, radius: null, teff: null, ...values };
	return { id, orbit: null, members: [], star } as unknown as SystemNode;
}

function pointPair(): Map<number, SystemNode> {
	const members = [
		{ id: HELD_A, kind: 'held star', gMag: null, vMag: null, mass: null },
		{ id: HELD_B, kind: 'held star', gMag: null, vMag: null, mass: null }
	];
	const node = {
		id: POINT,
		point: true,
		depth: 0,
		primary: POINT,
		distance: 10,
		orbit: orbit(),
		members
	} as unknown as SystemNode;
	return new Map([
		[POINT, node],
		[HELD_A, held(HELD_A, { mass: 2, radius: 0.65, teff: 4450 })],
		[HELD_B, held(HELD_B, { mass: 1, radius: null })]
	]);
}

function planOf(nodes: Map<number, SystemNode>, points: number[]): StarSystemPlan {
	const pairs = drawnPairs(nodes);
	const members = pairs.flatMap((p) => [p.node.id, p.first, p.second]);
	return { root: ROOT, nodes, points, pairs, ids: [...new Set([...points, ...members])] };
}

/** A scene that holds `bodies`. A body stays at its `position`. */
function scene(bodies: PositionedBody[], plan: StarSystemPlan) {
	const byId = new Map(bodies.map((b) => [b.data.id, b]));
	const notify = vi.fn();
	const ctx = {
		getBody: (id: string) => byId.get(id),
		place: (b: PositionedBody) => b.position,
		exoplanets: {
			index: null,
			loadIndex: async () => {},
			ensureStarSystem: async () => plan
		},
		bodies: { notifyBodiesAdded: notify, pinExtrasolar: () => {} },
		visibility: {}
	} as unknown as ContextManager;
	return { ctx, notify };
}

const frame = (focused: PositionedBody | undefined, cameraX: number, dtMs = 50): SystemsFrame => ({
	jd: 0,
	camera: [cameraX, 0, 0],
	viewportPx: 1000,
	fovDeg: 60,
	dtMs,
	outside: 1,
	focused
});

const landed = () => new Promise((resolve) => setTimeout(resolve));

/** A system with its pair at `apart` scene units, seen from `cameraX`. */
async function focusedSystem(apart: number) {
	const point = body(POINT, [0, 0, 0]);
	const a = body(HELD_A, [0, 0, 0]);
	const b = body(HELD_B, [0, apart, 0]);
	a.extrasolar!.tree = null;
	b.extrasolar!.tree = null;
	const plan = planOf(pointPair(), [POINT]);
	const { ctx, notify } = scene([point, a, b], plan);
	await holdStarSystem(ctx, plan);
	const system = new FocusedStarSystem(ctx, () => {});
	system.update(frame(point, 1e6));
	await landed();
	return { point, a, b, ctx, notify, system };
}

describe('loadStarSystem', () => {
	it('holds the root, which carries the halo of the system with no point or pair', async () => {
		const star = { id: 5, kind: 'star', orbit: null };
		rows.nodes = [{ id: ROOT, tree: [], orbit: null, depth: 0, members: [star] }];
		const plan = await loadStarSystem(ROOT);
		expect(plan.pairs).toEqual([]);
		expect(plan.ids).toEqual([ROOT, 5]);
	});
});

describe('holdStarSystem', () => {
	it('gives a held star its light, size and colour', async () => {
		const point = body(POINT, [0, 0, 0]);
		const a = body(HELD_A, [0, 0, 0]);
		const b = body(HELD_B, [0, 0, 0]);
		const plan = planOf(pointPair(), [POINT]);
		await holdStarSystem(scene([point, a, b], plan).ctx, plan);
		expect(a.extrasolar!.radiusKm).toBeCloseTo(0.65 * SOLAR_RADIUS_KM, 3);
		expect(a.data.radiusKm).toBeCloseTo(0.65 * SOLAR_RADIUS_KM, 3);
		expect(a.extrasolar!.teff).toBe(4450);
		expect(a.extrasolar!.colour).not.toBe(1);
		expect(b.extrasolar!.radiusKm).toBeNull();
		expect(b.extrasolar!.colour).toBe(1);
		// Masses 2 and 1: the first star takes 2^3.5 of 2^3.5 + 1 of the light.
		const light = (mag: number) => 10 ** (-0.4 * mag);
		expect(light(a.extrasolar!.absMag!) + light(b.extrasolar!.absMag!)).toBeCloseTo(light(5), 9);
		expect(b.extrasolar!.absMag! - a.extrasolar!.absMag!).toBeCloseTo(8.75 * Math.log10(2), 9);
		expect(a.data.starColor).toMatch(/^rgb/);
	});

	it('puts a resolved pair at the weighted places of its members', async () => {
		const root = body(ROOT, [9, 9, 9]);
		const a = body(21, [10, 0, 0]);
		const b = body(22, [0, 10, 0]);
		const node = {
			id: ROOT,
			point: false,
			depth: 0,
			primary: 21,
			distance: 10,
			orbit: orbit({ barycentre: 0.25 }),
			members: [
				{ id: 21, kind: 'star', gMag: null, vMag: null, mass: null },
				{ id: 22, kind: 'star', gMag: null, vMag: null, mass: null }
			]
		} as unknown as SystemNode;
		const plan = planOf(new Map([[ROOT, node]]), [21, 22]);
		await holdStarSystem(scene([root, a, b], plan).ctx, plan);
		expect(root.extrasolar!.scene).toEqual([7.5, 2.5, 0]);
		expect(a.extrasolar!.absMag).toBe(5);
	});

	it('drops a pair with a member that has no body', async () => {
		const point = body(POINT, [0, 0, 0]);
		const a = body(HELD_A, [0, 0, 0]);
		const plan = planOf(pointPair(), [POINT]);
		const held = await holdStarSystem(scene([point, a], plan).ctx, plan);
		expect(held.pairs).toEqual([]);
	});
});

describe('a pair inside a point', () => {
	const INNER = 20;
	const INNER_A = 21;
	const INNER_B = 22;

	/** One point that holds a star and a resolved pair. */
	async function triple() {
		const nodes = pointPair();
		const outer = nodes.get(POINT)!;
		const light = { gMag: null, vMag: null, mass: 2 };
		outer.members = [
			{ ...outer.members[0], ...light },
			{ ...outer.members[1], id: INNER, kind: 'system', ...light }
		];
		nodes.set(INNER, {
			id: INNER,
			point: false,
			depth: 1,
			primary: POINT,
			distance: 10,
			orbit: orbit(),
			star: null,
			members: [
				{ id: INNER_A, kind: 'held star', gMag: null, vMag: null, mass: null },
				{ id: INNER_B, kind: 'held star', gMag: null, vMag: null, mass: null }
			]
		} as unknown as SystemNode);
		nodes.set(INNER_A, held(INNER_A));
		nodes.set(INNER_B, held(INNER_B));
		const point = body(POINT, [0, 0, 0]);
		const star = body(HELD_A, [0, 10, 0]);
		const inner = body(INNER, [0, -10, 0]);
		const innerA = body(INNER_A, [0, -10, 0.1]);
		const innerB = body(INNER_B, [0, -10, -0.1]);
		for (const b of [star, inner, innerA, innerB]) b.extrasolar!.tree = null;
		const plan = planOf(nodes, [POINT]);
		const { ctx } = scene([point, star, inner, innerA, innerB], plan);
		await holdStarSystem(ctx, plan);
		const system = new FocusedStarSystem(ctx, () => {});
		system.update(frame(point, 1e6));
		await landed();
		return { point, star, innerA, innerB, system };
	}

	it('splits the light of the point among all its stars', async () => {
		const { star, innerA, innerB } = await triple();
		const flux = (b: PositionedBody) => 10 ** (-0.4 * b.extrasolar!.absMag!);
		expect(flux(star) + flux(innerA) + flux(innerB)).toBeCloseTo(10 ** (-0.4 * 5), 9);
		expect(flux(innerA)).toBeCloseTo(flux(innerB), 9);
		expect(flux(star)).toBeCloseTo(2 * flux(innerA), 9);
	});

	it('hands the light over as the outer pair parts, and adds up in the fade', async () => {
		const { point, star, innerA, innerB, system } = await triple();
		const light = (b: PositionedBody) => b.extrasolar!.light;
		for (let i = 0; i < 20; i++) system.update(frame(point, 1e6));
		expect([light(point), light(star), light(innerA), light(innerB)]).toEqual([1, 0, 0, 0]);
		for (let i = 0; i < 20; i++) system.update(frame(point, 200));
		expect([light(point), light(star), light(innerA), light(innerB)]).toEqual([0, 1, 1, 1]);
		system.update(frame(undefined, 200, 100));
		expect(light(innerA)).toBeGreaterThan(0);
		expect(light(innerA)).toBeLessThan(1);
		expect(light(innerB)).toBe(light(star));
		expect(light(innerA)).toBe(light(star));
		expect(light(point)! + light(star)!).toBeCloseTo(1, 12);
	});

	it('leaves no light behind when the system goes', async () => {
		const { point, innerA, system } = await triple();
		for (let i = 0; i < 20; i++) system.update(frame(point, 200));
		for (let i = 0; i < 10; i++) system.update(frame(undefined, 200, 100));
		expect(innerA.extrasolar!.light).toBeUndefined();
		expect(innerA.extrasolar!.drawnAt).toBeUndefined();
		expect(point.extrasolar!.light).toBeUndefined();
	});
});

describe('a star on the barycentre of its pair', () => {
	/** A system whose primary stays on the centre, as Procyon A does. */
	async function centred() {
		const nodes = pointPair();
		nodes.get(POINT)!.orbit = orbit({ barycentre: 0 });
		const point = body(POINT, [0, 0, 0]);
		const a = body(HELD_A, [0, 0, 0]);
		const b = body(HELD_B, [0, 10, 0]);
		a.extrasolar!.tree = null;
		b.extrasolar!.tree = null;
		const plan = planOf(nodes, [POINT]);
		const { ctx } = scene([point, a, b], plan);
		const system = new FocusedStarSystem(ctx, () => {});
		system.update(frame(point, 1e6));
		await landed();
		return { point, a, b, ctx, plan, system };
	}

	it('stands in for the halo of the node, and of a node at its place', async () => {
		const { b, system } = await centred();
		expect(system.haloOf(POINT)).toBe(HELD_A);
		expect(system.haloOf(HELD_B)).toBe(HELD_B);
		b.extrasolar!.scene = [0, 0, 0];
		expect(system.haloOf(HELD_B)).toBe(HELD_A);
	});

	it('carries the halo of the system, whichever body is focused', async () => {
		const { point, a, b, system } = await centred();
		for (const focused of [point, a, b]) {
			system.update(frame(focused, 1e6));
			expect(system.centres.get('x-11')).toBe(1);
			expect(system.centres.get('x-1')).toBe(0);
		}
	});

	it('leaves a pair with a real barycentre to its centre', async () => {
		const { a, b, point, system } = await focusedSystem(10);
		system.update(frame(b, 1e6));
		expect([...system.centres]).toEqual([['x-1', 1]]);
		system.update(frame(point, 1e6));
		expect([...system.centres]).toEqual([['x-1', 1]]);
		system.update(frame(a, 1e6));
		expect(system.centres.get('x-11')).toBeUndefined();
	});

	it('keeps a star as the halo of the system while the orbit fades out', async () => {
		const { point, system } = await centred();
		for (let i = 0; i < 10; i++) system.update(frame(point, 100));
		system.update(frame(undefined, 100, 100));
		expect(system.centres.get('x-11')).toBe(1);
		for (let i = 0; i < 10; i++) system.update(frame(undefined, 100, 100));
		expect(system.centres.size).toBe(0);
	});

	it('gives the halo of a focused inner pair to its star, and keeps the centre', async () => {
		const INNER = 20;
		const INNER_A = 21;
		const INNER_B = 22;
		const nodes = pointPair();
		const held2 = (id: number) => ({ id, kind: 'star', gMag: null, vMag: null, mass: null });
		nodes.get(POINT)!.members[1] = { ...nodes.get(POINT)!.members[1], id: INNER, kind: 'system' };
		nodes.set(INNER, {
			id: INNER,
			point: false,
			depth: 1,
			primary: INNER_A,
			distance: 10,
			orbit: orbit({ barycentre: 0 }),
			star: null,
			members: [held2(INNER_A), held2(INNER_B)]
		} as unknown as SystemNode);
		const point = body(POINT, [0, 0, 0]);
		const a = body(HELD_A, [0, 0, 0]);
		const inner = body(INNER, [0, 50, 0]);
		const innerA = body(INNER_A, [0, 50, 0]);
		const innerB = body(INNER_B, [0, 60, 0]);
		const plan = planOf(nodes, [POINT, INNER_A, INNER_B]);
		const { ctx } = scene([point, a, inner, innerA, innerB], plan);
		const system = new FocusedStarSystem(ctx, () => {});
		system.update(frame(inner, 1e6));
		await landed();
		system.update(frame(inner, 1e6));
		expect(system.centres.get('x-1')).toBe(1);
		expect(system.centres.get(`x-${INNER}`)).toBe(0);
		expect(system.centres.get(`x-${INNER_A}`)).toBe(1);
		system.update(frame(point, 1e6));
		expect(system.centres.has(`x-${INNER}`)).toBe(false);
	});

	it('builds the star, and not the node, for the scene', async () => {
		const { point, ctx } = await centred();
		const promotion = { syncSystemBodies: vi.fn() } as unknown as PromotionRegistry;
		const systems = new ExoplanetSystems(ctx, promotion, () => {});
		systems.update(frame(point, 1e6));
		await landed();
		systems.update(frame(point, 1e6));
		const built = vi.mocked(promotion.syncSystemBodies).mock.lastCall?.[0];
		expect(built?.map((b) => b.data.id)).toEqual(['x-11']);
		expect(ctx.visibility.systemCentres.get('x-11')).toBe(1);
		expect(ctx.visibility.systemCentres.get('x-1')).toBe(0);
	});
});

describe('the planets of a focused star', () => {
	const OTHER_ROOT = 900;
	const OTHER = 901;

	/** System `ROOT` has planets on its point. `OTHER` is in a system with none. */
	async function twoSystems() {
		const { point, a, b, ctx } = await focusedSystem(10);
		const root = body(OTHER_ROOT, [500, 0, 0], OTHER_ROOT);
		const other = body(OTHER, [500, 0, 0], OTHER_ROOT);
		const known = new Map([point, a, b, root, other].map((star) => [star.data.id, star] as const));
		const planOfRoot = planOf(pointPair(), [POINT]);
		const empty = { ...planOf(new Map(), [OTHER]), root: OTHER_ROOT };
		const use = vi.fn();
		const hostOfPoint = { id: POINT, system: ROOT, planets: [1], position: null };
		Object.assign(ctx, { getBody: (id: string) => known.get(id) });
		Object.assign(ctx.exoplanets, {
			index: {
				file: { hosts: [] },
				host: (id: number) => (id === POINT ? hostOfPoint : undefined),
				hostsOf: (key: number) => (key === ROOT ? [POINT] : [])
			},
			ensureHost: async () => null,
			ensureStarSystem: async (id: number) => (id === ROOT ? planOfRoot : empty),
			held: () => null,
			use
		});
		const promotion = { syncSystemBodies: () => {} } as unknown as PromotionRegistry;
		const systems = new ExoplanetSystems(ctx, promotion, () => {});
		return { point, a, other, systems, use };
	}

	it('takes the file of the root for a star on a drawn orbit with no planets', async () => {
		const { a, systems, use } = await twoSystems();
		systems.update(frame(a, 100));
		await landed();
		systems.update(frame(a, 100));
		expect([...use.mock.lastCall![0]]).toEqual([ROOT]);
	});

	it('takes no file from a system that fades out', async () => {
		const { a, other, systems, use } = await twoSystems();
		systems.update(frame(a, 100));
		await landed();
		for (let i = 0; i < 10; i++) systems.update(frame(a, 100));
		systems.update(frame(other, 100, 16));
		expect(systems.fading).toBe(true);
		expect([...use.mock.lastCall![0]]).toEqual([]);
	});
});

describe('a star on no drawn orbit', () => {
	it('shows by its distance from the centre, the primary carrying the system', async () => {
		const root = {
			id: ROOT,
			point: false,
			depth: 0,
			primary: 21,
			distance: 10,
			orbit: null,
			members: [
				{ id: 21, kind: 'star', gMag: null, vMag: null, mass: null },
				{ id: 22, kind: 'star', gMag: null, vMag: null, mass: null }
			]
		} as unknown as SystemNode;
		const a = body(21, [100, 0, 0]);
		const b = body(22, [100, 300, 0]);
		const plan = planOf(new Map([[ROOT, root]]), [21, 22]);
		const { ctx } = scene([body(ROOT, [100, 0, 0]), a, b], plan);
		const system = new FocusedStarSystem(ctx, () => {});
		system.update(frame(a, 1e6));
		await landed();
		system.update(frame(a, 1e6));
		expect(b.extrasolar!.pairAxis).toBeCloseTo(30, 9);
		expect(system.shares.get('x-22')).toBe(1);
		expect(system.shares.has('x-21')).toBe(false);
		expect(system.centres.get(`x-${ROOT}`)).toBe(0);
		expect(system.centres.get('x-21')).toBe(1);

		system.update(frame(body(9, [0, 0, 0], 0), 1e6));
		expect(b.extrasolar!.pairAxis).toBeUndefined();
		expect(system.shares.size).toBe(0);
	});
});

describe('FocusedStarSystem', () => {
	it('puts the two members on their orbits about the pair', async () => {
		const { a, b, system } = await focusedSystem(1);
		system.update(frame(a, 1e6));
		expect(a.data.parentId).toBe('x-1');
		expect(a.data.a).toBeCloseTo(0.5, 12);
		expect(a.data.w).toBe(180);
		expect(b.data.a).toBeCloseTo(1.5, 12);
		expect(a.orbitElements).toBe(a.data);
		expect(a.orbitCenterId).toBe('x-1');
		expect(a.extrasolar!.drawnAt).toEqual(a.position);
		expect(a.extrasolar!.pairAxis).toBe(2);
		expect(b.extrasolar!.pairAxis).toBe(2);
	});

	it('leaves a primary with no mass ratio on the centre, with no line', async () => {
		const nodes = pointPair();
		nodes.get(POINT)!.orbit = orbit({ barycentre: 0 });
		const point = body(POINT, [0, 0, 0]);
		const a = body(HELD_A, [0, 0, 0]);
		const b = body(HELD_B, [0, 1, 0]);
		const plan = planOf(nodes, [POINT]);
		const { ctx } = scene([point, a, b], plan);
		const system = new FocusedStarSystem(ctx, () => {});
		system.update(frame(point, 1e6));
		await landed();
		system.update(frame(point, 1e6));
		expect(a.data.a).toBe(0);
		expect(a.data.parentId).toBe('x-1');
		expect(a.orbitElements).toBeUndefined();
		expect(b.orbitElements).toBe(b.data);
	});

	it('hands the light of the point to the stars as they part on screen', async () => {
		const { point, a, b, system } = await focusedSystem(10);
		// 1,000 px over 60°: 866 px per radian, so 10 units from 1e6 is under a pixel.
		for (let i = 0; i < 20; i++) system.update(frame(point, 1e6));
		expect(point.extrasolar!.light).toBe(1);
		expect(a.extrasolar!.light).toBe(0);
		// Close enough for 20 px apart.
		for (let i = 0; i < 20; i++) system.update(frame(point, 433));
		expect(point.extrasolar!.light).toBe(0);
		expect(b.extrasolar!.light).toBe(1);
		// Between the two, the light is shared.
		system.update(frame(point, 2165));
		const share = a.extrasolar!.light!;
		expect(share).toBeGreaterThan(0);
		expect(share).toBeLessThan(1);
		expect(point.extrasolar!.light).toBeCloseTo(1 - share, 9);
	});

	it('shows the halos and the lines while the orbit is wide enough on screen', async () => {
		const { point, system } = await focusedSystem(10);
		system.update(frame(point, 1e12));
		expect(system.shares.size).toBe(0);
		for (let i = 0; i < 10; i++) system.update(frame(point, 100));
		expect([...system.shares.keys()].sort()).toEqual(['x-11', 'x-12']);
		expect(system.shares.get('x-11')).toBe(1);
	});

	it('fades the pair out after the focus leaves, then takes the stars off it', async () => {
		const { point, a, b, notify, system } = await focusedSystem(10);
		for (let i = 0; i < 10; i++) system.update(frame(point, 100));
		notify.mockClear();
		// One step of the fade: the stars stay, for now.
		system.update(frame(undefined, 100, 100));
		expect(a.data.parentId).toBe('x-1');
		expect(a.extrasolar!.light).toBeGreaterThan(0);
		expect(a.extrasolar!.light).toBeLessThan(1);
		expect(system.stars.map((s) => s.id).sort()).toEqual([POINT, HELD_A, HELD_B]);
		expect(system.fading).toBe(true);
		for (let i = 0; i < 10; i++) system.update(frame(undefined, 100, 100));
		expect(a.data.parentId).toBe('');
		expect(a.orbitElements).toBeUndefined();
		expect(a.orbitCenter).toBeNull();
		expect(a.extrasolar!.drawnAt).toBeUndefined();
		expect(a.extrasolar!.pairAxis).toBeUndefined();
		expect(b.extrasolar!.light).toBeUndefined();
		expect(point.extrasolar!.light).toBeUndefined();
		expect(notify).toHaveBeenCalledTimes(1);
		expect(system.stars).toEqual([]);
	});

	it('keeps the point exact through the fade, with its light and the stars adding up', async () => {
		const { point, a, b, system } = await focusedSystem(10);
		for (let i = 0; i < 10; i++) system.update(frame(point, 100));
		expect(point.extrasolar!.light).toBe(0);
		let last = 0;
		for (let i = 0; i < 6; i++) {
			system.update(frame(undefined, 100, 50));
			const light = point.extrasolar!.light!;
			expect(light + a.extrasolar!.light!).toBeCloseTo(1, 12);
			expect(b.extrasolar!.light).toBe(a.extrasolar!.light);
			expect(system.stars).toContain(point.extrasolar);
			expect(light).toBeGreaterThan(last);
			expect(light - last).toBeLessThan(0.3);
			last = light;
		}
		system.update(frame(undefined, 100, 50));
		expect(point.extrasolar!.light).toBeUndefined();
		expect(system.stars).toEqual([]);
	});

	it('shows the centre of the system with the focus on a star of it', async () => {
		const { b, system } = await focusedSystem(10);
		system.update(frame(b, 1e6));
		expect([...system.centres]).toEqual([['x-1', 1]]);
	});

	it('shows the centre with no share of its orbits to carry it', async () => {
		const { b, system } = await focusedSystem(10);
		system.update(frame(b, 1e12));
		expect(system.shares.size).toBe(0);
		expect(system.centres.get('x-1')).toBe(1);
	});

	it('shows one halo while the focused body sits on the centre', async () => {
		const { point, a, system } = await focusedSystem(10);
		system.update(frame(a, 1e6));
		expect(system.centres.get('x-1')).toBe(0);
		system.update(frame(point, 1e6));
		expect(system.centres.get('x-1')).toBe(1);
	});

	it('takes the centre away with the last orbit of the system', async () => {
		const { point, system } = await focusedSystem(10);
		for (let i = 0; i < 10; i++) system.update(frame(point, 100));
		system.update(frame(undefined, 100, 100));
		expect(system.centres.get('x-1')).toBe(1);
		for (let i = 0; i < 10; i++) system.update(frame(undefined, 100, 100));
		expect(system.centres.size).toBe(0);
	});

	it('has no centre with no focus in a system', () => {
		const point = body(POINT, [0, 0, 0]);
		const { ctx } = scene([point], planOf(pointPair(), [POINT]));
		const system = new FocusedStarSystem(ctx, () => {});
		system.update(frame(undefined, 100));
		expect(system.centres.size).toBe(0);
	});

	it('draws a held star on an orbit on its own, and its point too', async () => {
		const point = body(POINT, [0, 0, 0]);
		const a = body(HELD_A, [0, 0, 0]);
		const b = body(HELD_B, [0, 10, 0]);
		a.extrasolar!.tree = null;
		b.extrasolar!.tree = null;
		const plan = planOf(pointPair(), [POINT]);
		const { ctx } = scene([point, a, b], plan);
		const promotion = { syncSystemBodies: vi.fn() } as unknown as PromotionRegistry;
		const systems = new ExoplanetSystems(ctx, promotion, () => {});
		systems.update(frame(a, 100));
		await landed();
		for (let i = 0; i < 10; i++) systems.update(frame(a, 100));
		const exact = systems.exactStars(a);
		const ids = [...exact, ...systems.companions(exact)].map((star) => star.id);
		expect(ids[0]).toBe(HELD_A);
		expect([...ids].sort()).toEqual([POINT, HELD_A, HELD_B].sort());
		const drawn = vi.mocked(promotion.syncSystemBodies).mock.lastCall?.[0];
		expect(drawn?.map((body) => body.data.id)).toEqual(['x-11', 'x-12']);
		expect(ctx.visibility.systemShares.get('x-12')).toBe(1);
	});
});
