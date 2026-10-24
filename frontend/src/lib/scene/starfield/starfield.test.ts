/**
 * The starfield's walk of the render tree: which nodes it fetches, the
 * limit a point budget leaves, and the gates that keep it from fetching.
 * Then what a pick pass draws, and how a picked row becomes an ID.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BufferGeometry, PerspectiveCamera, Points, Scene, type ShaderMaterial } from 'three';
import { FOCUS_FLOOR_MAG, NO_FLOOR, makeStarMaterial, starUniforms } from './material';
import { Container } from '$lib/fetch/extrasolar/container';
import type { ExtrasolarMetadata, ExtrasolarTree } from '$lib/fetch/extrasolar/files';
import { LayerSet } from '$lib/scene/layers';
import { PickRegistry } from '$lib/scene/interaction/pick-registry';
import { encode } from '$lib/fetch/extrasolar/__fixtures__/writer';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { treeToScene, type Vec3 } from './tree';

const TOKEN = '0123456789abcdef';

interface FakeNode {
	centre: Vec3;
	half: number;
	/** Largest range of its rows, which its parent lists for it. */
	range: number;
	childRange: number[];
	rows: number;
}

/** A render node payload: the container header, the 80-byte info block and
 *  the seven columns of the `mw` tree. */
function encodeNode(node: FakeNode, depth: number): ArrayBuffer {
	const columns = ['x', 'y', 'z', 'range', 'mag', 'colour', 'class'];
	const n = node.rows;
	const pad = (v: number) => v + ((8 - (v % 8)) % 8);
	let dir = 0;
	for (const name of columns) dir += 4 + name.length + 8;
	let at = pad(32 + 80 + dir);
	const places = columns.map((name) => {
		const length = name === 'class' ? n : 4 * n;
		const place = { offset: at, length };
		at = pad(at + length);
		return place;
	});
	const buffer = new ArrayBuffer(at);
	const view = new DataView(buffer);
	const bytes = new Uint8Array(buffer);
	bytes.set(new TextEncoder().encode('SMXS'), 0);
	view.setUint16(4, 1, true);
	view.setUint8(6, 3);
	bytes.set(new TextEncoder().encode(TOKEN), 8);
	view.setUint32(24, n, true);
	view.setUint16(28, columns.length, true);
	view.setUint16(30, 80, true);
	node.centre.forEach((c, i) => view.setFloat64(32 + 8 * i, c, true));
	view.setFloat64(56, node.half, true);
	view.setFloat32(64, node.range, true);
	view.setFloat32(68, node.range, true);
	node.childRange.forEach((r, k) => view.setFloat32(72 + 4 * k, r, true));
	view.setUint8(104, depth);
	view.setUint8(
		105,
		node.childRange.reduce((mask, r, k) => (r > 0 ? mask | (1 << k) : mask), 0)
	);
	let d = 112;
	columns.forEach((name, c) => {
		view.setUint8(d, name === 'class' ? 5 : 8);
		view.setUint8(d + 2, 1);
		view.setUint8(d + 3, name.length);
		bytes.set(new TextEncoder().encode(name), d + 4);
		d += 4 + name.length;
		view.setUint32(d, places[c].offset, true);
		view.setUint32(d + 4, places[c].length, true);
		d += 8;
	});
	new Float32Array(buffer, places[4].offset, n).fill(10);
	return buffer;
}

const HALF = 1000;
/** The tree's centre. The barycentre is in child 0's box, 900 pc from the
 *  centre on each axis, so a camera near the Sun sees that geometry. */
const C = 900;
const nodes = new Map<string, FakeNode>();
const fetched: string[] = [];
/** ID of row i of node `name`: one per row, never 0. */
const rowId = (name: string, row: number) => 1e9 * name.length + 1000 * row + 7;
let allow = true;
let metadataCalls = 0;
/** Metadata fetches that throw before one succeeds. */
let metadataFailures = 0;
let treeListed = true;
let skipStars = false;
let base = '/x';

const tree: ExtrasolarTree = {
	token: TOKEN,
	root: 'mw/node/r.bin.gz',
	node: 'mw/node/{name}.bin.gz',
	ids: 'mw/id/{name}.bin.gz',
	centre: [C, C, C],
	half_size: HALF,
	node_rows: 100,
	range_limit_mag: 6.5,
	units: 'pc',
	frame: 'ICRS',
	classes: { star: 1 },
	nodes: 9,
	depth: 1,
	rows: 900,
	columns: [],
	id_columns: [],
	distribution: 'non-commercial'
};

vi.mock('$lib/scene/setup/load-gates', () => ({ eagerMinorsDone: Promise.resolve() }));
vi.mock('$lib/fetch/extrasolar/files', async (importActual) => {
	const actual = await importActual<typeof import('$lib/fetch/extrasolar/files')>();
	return {
		...actual,
		extrasolarBase: () => base,
		extrasolarAllowed: () => allow,
		fetchExtrasolarMetadata: async (): Promise<ExtrasolarMetadata> => {
			metadataCalls++;
			if (metadataFailures > 0) {
				metadataFailures--;
				throw new Error('extrasolar metadata.json returned 503');
			}
			return {
				format: 1,
				exported: '',
				registry: { ingest: 1, host: 'test' },
				tables: {},
				trees: treeListed ? { mw: tree } : {},
				credits: [{ name: 'Gaia', organisation: 'ESA', source: 'https://x', license: 'CC' }]
			};
		},
		fetchExtrasolarFile: async (path: string) => {
			if (path.startsWith('mw/id/')) {
				const name = path.replace('mw/id/', '').replace('.bin.gz', '');
				fetched.push(`id:${name}`);
				const node = nodes.get(name);
				if (!node) throw new Error(`no ID file ${name}`);
				const values = Array.from({ length: node.rows }, (_, i) => rowId(name, i));
				const payload = encode(4, TOKEN, node.rows, [{ name: 'id', type: 'id', values }]);
				return new Container(payload.buffer as ArrayBuffer);
			}
			const name = path.replace('mw/node/', '').replace('.bin.gz', '');
			fetched.push(name);
			const node = nodes.get(name);
			if (!node) throw new Error(`no node ${name}`);
			return new Container(encodeNode(node, name.length - 1));
		}
	};
});

const { StarfieldSystem } = await import('./starfield');

function fakeCtx(): ContextManager {
	const layers = new LayerSet(skipStars ? { starfield: false } : {});
	return {
		layers,
		onDataStale: null,
		credits: { setStars: vi.fn() }
	} as unknown as ContextManager;
}

/** Root with eight children; child k's range from `ranges`. */
function buildTree(ranges: number[], rows = 100): void {
	nodes.clear();
	nodes.set('r', { centre: [C, C, C], half: HALF, range: 1e4, childRange: ranges, rows });
	for (let k = 0; k < 8; k++) {
		const q = HALF / 2;
		const centre: Vec3 = [C + (k & 1 ? q : -q), C + (k & 2 ? q : -q), C + (k & 4 ? q : -q)];
		nodes.set(`r${k}`, {
			centre,
			half: q,
			range: ranges[k],
			childRange: new Array(8).fill(0),
			rows
		});
	}
}

let clock = 1000;

async function settle(
	system: InstanceType<typeof StarfieldSystem>,
	camera: PerspectiveCamera,
	focus: Vec3
): Promise<void> {
	for (let i = 0; i < 20; i++) {
		clock += 200;
		system.update(camera, focus, 1, 1, clock);
		await new Promise((resolve) => setTimeout(resolve, 0));
	}
}

/** The camera in child 0's box, 0.1 pc from the barycentre (past the band,
 *  under the 1 pc of the base limit), zoomed in. */
function setup(): { camera: PerspectiveCamera; focus: Vec3 } {
	const at = treeToScene(0.1, 0, 0, { x: 0, y: 0, z: 0 });
	const camera = new PerspectiveCamera(60, 1, 1e-6, 1e12);
	camera.position.set(0, 0, 1e-3);
	camera.updateMatrixWorld();
	return { camera, focus: [at.x, at.y, at.z] };
}

beforeEach(() => {
	fetched.length = 0;
	metadataCalls = 0;
	metadataFailures = 0;
	treeListed = true;
	allow = true;
	skipStars = false;
	base = '/x';
});

afterEach(() => {
	vi.useRealTimers();
	vi.restoreAllMocks();
});

describe('the starfield walk', () => {
	it('loads the boxes whose brightest possible star is over the limit', async () => {
		// Child 7 is 1559 pc away: range 1000 pc shows at 7.46, under the 7.5 limit.
		// Child 1 is 900 pc away: range 500 pc shows at 7.78, over it.
		buildTree([10, 500, 10, 10, 10, 10, 10, 1000]);
		const { camera, focus } = setup();
		const system = new StarfieldSystem(
			fakeCtx(),
			new Scene(),
			{ points: 1e6, bytes: 1e9, fetches: 8 },
			() => {},
			new PickRegistry()
		);
		await settle(system, camera, focus);
		expect(new Set(fetched)).toEqual(new Set(['r', 'r0', 'r7']));
		expect(system.stats().drawnNodes).toBe(3);
		expect(system.availability()).toBe('yes');
		expect(system.stats().limit).toBeCloseTo(7.5, 2);
	});

	it('lowers the limit to the first box the point budget leaves out', async () => {
		buildTree([10, 500, 10, 10, 10, 10, 10, 1000]);
		const { camera, focus } = setup();
		// Root and child 0 hold the camera and load whatever the budget.
		const system = new StarfieldSystem(
			fakeCtx(),
			new Scene(),
			{ points: 150, bytes: 1e9, fetches: 8 },
			() => {},
			new PickRegistry()
		);
		await settle(system, camera, focus);
		expect(new Set(fetched)).toEqual(new Set(['r', 'r0']));
		expect(system.stats().limit).toBeCloseTo(6.5 + 5 * Math.log10((900 * Math.sqrt(3)) / 1000), 2);
	});

	it('fetches nothing for a layer switched off at open time', async () => {
		skipStars = true;
		buildTree(new Array(8).fill(10));
		const { camera, focus } = setup();
		const system = new StarfieldSystem(
			fakeCtx(),
			new Scene(),
			{ points: 1e6, bytes: 1e9, fetches: 8 },
			() => {},
			new PickRegistry()
		);
		await settle(system, camera, focus);
		expect(fetched).toEqual([]);
		expect(system.availability()).toBe('no');
	});

	it('keeps the camera in the solar system without an extrasolar base', () => {
		base = '';
		const system = new StarfieldSystem(
			fakeCtx(),
			new Scene(),
			{ points: 1e6, bytes: 1e9, fetches: 8 },
			() => {},
			new PickRegistry()
		);
		expect(system.availability()).toBe('no');
	});

	it('fetches nothing when a layer switched off at open time is switched on', async () => {
		skipStars = true;
		buildTree(new Array(8).fill(10));
		const { camera, focus } = setup();
		const ctx = fakeCtx();
		const system = new StarfieldSystem(
			ctx,
			new Scene(),
			{ points: 1e6, bytes: 1e9, fetches: 8 },
			() => {},
			new PickRegistry()
		);
		await settle(system, camera, focus);
		ctx.layers.setVisible('starfield', true);
		await settle(system, camera, focus);
		expect(fetched).toEqual([]);
		expect(system.group.visible).toBe(false);
	});

	it('sends no request on a runtime switch, which only decides what draws', async () => {
		buildTree([10, 500, 10, 10, 10, 10, 10, 1000]);
		const { camera, focus } = setup();
		const ctx = fakeCtx();
		ctx.layers.setVisible('starfield', false);
		const system = new StarfieldSystem(
			ctx,
			new Scene(),
			{ points: 1e6, bytes: 1e9, fetches: 8 },
			() => {},
			new PickRegistry()
		);
		// Hidden, the nodes still follow the camera.
		await settle(system, camera, focus);
		expect(new Set(fetched)).toEqual(new Set(['r', 'r0', 'r7']));
		expect(system.group.visible).toBe(false);
		const requests = fetched.length;
		ctx.layers.setVisible('starfield', true);
		await settle(system, camera, focus);
		expect(system.group.visible).toBe(true);
		expect(system.stats().drawnNodes).toBe(3);
		ctx.layers.setVisible('starfield', false);
		await settle(system, camera, focus);
		expect(system.group.visible).toBe(false);
		expect(system.share()).toBe(0);
		// The skybox is the sky seen from the Sun, so it does not come back.
		expect(system.skyboxShare()).toBe(0);
		expect(fetched.length).toBe(requests);
	});

	it('fetches nothing, not even the metadata, inside the solar system', async () => {
		buildTree(new Array(8).fill(10));
		const camera = new PerspectiveCamera(60, 1, 1e-6, 1e12);
		// 1 AU from the barycentre, with the focus there.
		camera.position.set(10, 0, 0);
		camera.updateMatrixWorld();
		const system = new StarfieldSystem(
			fakeCtx(),
			new Scene(),
			{ points: 1e6, bytes: 1e9, fetches: 8 },
			() => {},
			new PickRegistry()
		);
		await settle(system, camera, [0, 0, 0]);
		expect(metadataCalls).toBe(0);
		expect(fetched).toEqual([]);
		expect(system.share()).toBe(0);
		expect(system.skyboxShare()).toBe(1);
		// Nothing to draw: the scene may rest.
		expect(system.busy()).toBe(false);
	});

	it('takes the sky past the band, and stops loading back inside it', async () => {
		buildTree([10, 500, 10, 10, 10, 10, 10, 1000]);
		const { camera, focus } = setup();
		const system = new StarfieldSystem(
			fakeCtx(),
			new Scene(),
			{ points: 1e6, bytes: 1e9, fetches: 8 },
			() => {},
			new PickRegistry()
		);
		await settle(system, camera, focus);
		expect(system.share()).toBeGreaterThan(0.99);
		expect(system.skyboxShare()).toBe(0);
		expect(system.stats().active).toBe(true);
		const requests = fetched.length;
		// Back to 1 AU from the barycentre.
		camera.position.set(10, 0, 0);
		await settle(system, camera, [0, 0, 0]);
		expect(system.stats().active).toBe(false);
		expect(system.share()).toBe(0);
		expect(system.skyboxShare()).toBe(1);
		expect(system.stats().drawnNodes).toBe(0);
		// What came in stays cached for the way out again.
		expect(system.stats().cachedNodes).toBe(3);
		expect(fetched.length).toBe(requests);
	});

	it('draws no star where it may not draw', async () => {
		allow = false;
		buildTree(new Array(8).fill(10));
		const { camera, focus } = setup();
		const system = new StarfieldSystem(
			fakeCtx(),
			new Scene(),
			{ points: 1e6, bytes: 1e9, fetches: 8 },
			() => {},
			new PickRegistry()
		);
		await settle(system, camera, focus);
		expect(system.share()).toBe(0);
		expect(system.skyboxShare()).toBe(0);
	});

	it('leaves no skybox while the stars load out of the solar system', async () => {
		buildTree(new Array(8).fill(10));
		const { camera, focus } = setup();
		const system = new StarfieldSystem(
			fakeCtx(),
			new Scene(),
			{ points: 1e6, bytes: 1e9, fetches: 8 },
			() => {},
			new PickRegistry()
		);
		system.update(camera, focus, 1, 1, (clock += 200));
		expect(system.stats().cachedNodes).toBe(0);
		expect(system.share()).toBe(0);
		expect(system.skyboxShare()).toBe(0);
		await settle(system, camera, focus);
		expect(system.share()).toBeGreaterThan(0.99);
	});

	it('fetches no node when the host may not serve the tree', async () => {
		allow = false;
		buildTree(new Array(8).fill(10));
		const { camera, focus } = setup();
		const system = new StarfieldSystem(
			fakeCtx(),
			new Scene(),
			{ points: 1e6, bytes: 1e9, fetches: 8 },
			() => {},
			new PickRegistry()
		);
		expect(system.availability()).toBe('unknown');
		await settle(system, camera, focus);
		expect(fetched).toEqual([]);
		expect(system.treeEntry()).toBeNull();
		expect(system.availability()).toBe('no');
	});

	it('draws no star when the metadata lists no tree', async () => {
		treeListed = false;
		const { camera, focus } = setup();
		const system = new StarfieldSystem(
			fakeCtx(),
			new Scene(),
			{ points: 1e6, bytes: 1e9, fetches: 8 },
			() => {},
			new PickRegistry()
		);
		await settle(system, camera, focus);
		expect(fetched).toEqual([]);
		expect(system.availability()).toBe('no');
	});

	it('tries the metadata again after a failed fetch', async () => {
		vi.useFakeTimers();
		metadataFailures = 1;
		buildTree([10, 500, 10, 10, 10, 10, 10, 1000]);
		const { camera, focus } = setup();
		const system = new StarfieldSystem(
			fakeCtx(),
			new Scene(),
			{ points: 1e6, bytes: 1e9, fetches: 8 },
			() => {},
			new PickRegistry()
		);
		const step = async (ms: number) => {
			for (let t = 0; t < ms; t += 200) {
				clock += 200;
				system.update(camera, focus, 1, 1, clock);
				await vi.advanceTimersByTimeAsync(200);
			}
		};
		await step(1000);
		// A failed fetch leaves the answer unknown.
		expect(metadataCalls).toBe(1);
		expect(system.availability()).toBe('unknown');
		await step(3000);
		expect(metadataCalls).toBe(2);
		expect(system.availability()).toBe('yes');
		expect(new Set(fetched)).toEqual(new Set(['r', 'r0', 'r7']));
	});

	it('gives a drawn row its scene position', async () => {
		buildTree(new Array(8).fill(10));
		const { camera, focus } = setup();
		const system = new StarfieldSystem(
			fakeCtx(),
			new Scene(),
			{ points: 1e6, bytes: 1e9, fetches: 8 },
			() => {},
			new PickRegistry()
		);
		await settle(system, camera, focus);
		const want = treeToScene(C - 500, C - 500, C - 500, { x: 0, y: 0, z: 0 });
		const got = system.rowPosition('r0', 0);
		expect(got?.[0]).toBeCloseTo(want.x, 0);
		expect(got?.[2]).toBeCloseTo(want.z, 0);
		expect(system.drawnNodes().map((n) => n.name)).toContain('r0');
	});

	it('draws the focused star on its own and hides its row in the node', async () => {
		buildTree(new Array(8).fill(10));
		const { camera, focus } = setup();
		const system = new StarfieldSystem(
			fakeCtx(),
			new Scene(),
			{ points: 1e6, bytes: 1e9, fetches: 8 },
			() => {},
			new PickRegistry()
		);
		await settle(system, camera, focus);
		const hidden = () =>
			Object.fromEntries(
				system
					.drawnNodes()
					.map((n) => [n.name, (n.points.material as ShaderMaterial).uniforms.uHidden.value])
			);
		const points = () => system.group.children.filter((c) => c.userData.focusStar !== undefined);
		// Every fake row sits at its node's centre with magnitude 10.
		system.setFocusStar({
			id: 7,
			record: null!,
			scene: [0, 0, 0],
			tree: [C - 500, C - 500, C - 500],
			absMag: 10,
			colour: null
		});
		expect(hidden()).toMatchObject({ r: -1, r0: 0 });
		expect(points()).toHaveLength(1);
		expect(points()[0].position.toArray()).toEqual([C - 500, C - 500, C - 500]);

		// Another magnitude is another star: nothing to hide.
		system.setFocusStar({
			id: 8,
			record: null!,
			scene: [0, 0, 0],
			tree: [C - 500, C - 500, C - 500],
			absMag: 3,
			colour: null
		});
		expect(hidden()).toMatchObject({ r: -1, r0: -1 });
		expect(points()).toHaveLength(1);

		system.setFocusStar(null);
		expect(hidden()).toMatchObject({ r: -1, r0: -1 });
		expect(points()).toHaveLength(0);
	});

	it('keeps local stars independent of the sky fade and layer switch', async () => {
		buildTree(new Array(8).fill(10));
		const { camera, focus } = setup();
		const ctx = fakeCtx();
		const system = new StarfieldSystem(
			ctx,
			new Scene(),
			{ points: 1e6, bytes: 1e9, fetches: 8 },
			() => {},
			new PickRegistry()
		);
		const material = makeStarMaterial(starUniforms());
		material.uniforms.uFade.value = 1;
		material.uniforms.uDistancePc.value = 0.01;
		const point = new Points(new BufferGeometry(), material);
		await settle(system, camera, focus);
		ctx.layers.setVisible('starfield', false);
		system.update(camera, focus, 2, 0.25, clock + 200);
		system.updateLocalStar(point, true);
		expect(material.uniforms.uLimit.value).toBe(system.stats().limit);
		expect(material.uniforms.uPixelRatio.value).toBe(2);
		expect(material.uniforms.uFloor.value).toBe(FOCUS_FLOOR_MAG);
		expect(material.uniforms.uGain.value).toBe(1);
		expect(material.uniforms.uFade.value).toBe(1);
		expect(material.uniforms.uDistancePc.value).toBe(0.01);
		system.updateLocalStar(point, false);
		expect(material.uniforms.uFloor.value).toBe(NO_FLOOR);
		system.dispose();
		point.geometry.dispose();
		material.dispose();
	});

	it('updates local star resolution without an extrasolar export', () => {
		base = '';
		const { camera, focus } = setup();
		const system = new StarfieldSystem(
			fakeCtx(),
			new Scene(),
			{ points: 1e6, bytes: 1e9, fetches: 8 },
			() => {},
			new PickRegistry()
		);
		const material = makeStarMaterial(starUniforms());
		const point = new Points(new BufferGeometry(), material);
		system.update(camera, focus, 3, 0, clock + 200);
		system.updateLocalStar(point, false);
		expect(material.uniforms.uPixelRatio.value).toBe(3);
		expect(material.uniforms.uGain.value).toBe(1);
		expect(system.share()).toBe(0);
		system.dispose();
		point.geometry.dispose();
		material.dispose();
	});

	it('draws no focus point for a star with no place', async () => {
		buildTree(new Array(8).fill(10));
		const { camera, focus } = setup();
		const system = new StarfieldSystem(
			fakeCtx(),
			new Scene(),
			{ points: 1e6, bytes: 1e9, fetches: 8 },
			() => {},
			new PickRegistry()
		);
		await settle(system, camera, focus);
		system.setFocusStar({
			id: 9,
			record: null!,
			scene: null,
			tree: null,
			absMag: null,
			colour: null
		});
		expect(system.group.children.some((c) => c.userData.focusStar !== undefined)).toBe(false);
	});
});

describe('picking a star', () => {
	async function drawn(registry = new PickRegistry()) {
		buildTree(new Array(8).fill(10));
		const { camera, focus } = setup();
		const system = new StarfieldSystem(
			fakeCtx(),
			new Scene(),
			{ points: 1e6, bytes: 1e9, fetches: 8 },
			() => {},
			registry
		);
		await settle(system, camera, focus);
		return { system, registry };
	}

	it('draws each drawn node with its own range and the uniforms it drew with', async () => {
		const { system, registry } = await drawn();
		const draws = system.pickDraws();
		expect(draws.length).toBeGreaterThan(0);
		expect(draws.length).toBe(system.drawnNodes().filter((n) => n.points.visible).length);
		const bases = new Set<number>();
		for (const { points, material } of draws) {
			const pick = (material as ShaderMaterial).uniforms;
			const draw = (points.material as ShaderMaterial).uniforms;
			// Same objects: the limit, the fade and the hidden row of the last draw.
			expect(pick.uLimit).toBe(draw.uLimit);
			expect(pick.uFade).toBe(draw.uFade);
			expect(pick.uHidden).toBe(draw.uHidden);
			// One pick pixel is one CSS pixel.
			expect(pick.uPixelRatio.value).toBe(1);
			expect((material as ShaderMaterial).vertexShader).toContain('vPick = uPickBase');
			bases.add(pick.uPickBase.value);
			const name = points.userData.starNode as string;
			expect(system.pickedStar(pick.uPickBase.value + 3)).toEqual({ node: name, row: 3 });
			expect(registry.resolve(pick.uPickBase.value + 3)).toBeNull();
		}
		expect(bases.size).toBe(draws.length);
		// A second pick reuses the ranges and the materials.
		const again = system.pickDraws();
		expect(again.map((d) => d.material)).toEqual(draws.map((d) => d.material));
	});

	it('reads a row ID from the node ID file, loaded once', async () => {
		const { system } = await drawn();
		const before = system.stats().cachedBytes;
		// Two clicks before the file is in share one load.
		const [a, b] = await Promise.all([
			system.starId({ node: 'r0', row: 5 }),
			system.starId({ node: 'r0', row: 6 })
		]);
		expect([a, b]).toEqual([rowId('r0', 5), rowId('r0', 6)]);
		expect(await system.starId({ node: 'r0', row: 0 })).toBe(rowId('r0', 0));
		expect(fetched.filter((f) => f === 'id:r0')).toHaveLength(1);
		expect(system.stats().cachedBytes).toBeGreaterThan(before);
	});

	it('picks the focused star as that star', async () => {
		const { system } = await drawn();
		system.setFocusStar({
			id: 22137869,
			record: null!,
			scene: [0, 0, 0],
			tree: [C - 500, C - 500, C - 500],
			absMag: 10,
			colour: null
		});
		const focusDraw = system.pickDraws().find((d) => d.points.userData.focusStar !== undefined);
		const base = (focusDraw?.material as ShaderMaterial).uniforms.uPickBase.value;
		expect(system.pickedStar(base)).toEqual({ id: 22137869 });
		expect(await system.starId({ id: 22137869 })).toBe(22137869);
		// A new focus takes a new range; the old one names nothing.
		system.setFocusStar(null);
		expect(system.pickedStar(base)).toBeNull();
	});

	it('draws nothing to pick where the stars do not draw', async () => {
		const { system } = await drawn();
		expect(system.pickDraws().length).toBeGreaterThan(0);
		system.group.visible = false;
		expect(system.pickDraws()).toEqual([]);
	});

	it('gives back every range when it goes', async () => {
		const { system } = await drawn();
		const bases = system
			.pickDraws()
			.map((d) => (d.material as ShaderMaterial).uniforms.uPickBase.value as number);
		system.dispose();
		for (const base of bases) expect(system.pickedStar(base)).toBeNull();
	});
});
