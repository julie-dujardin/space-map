/**
 * The life of `GlowSky`: when it loads, when it marches, when it rests, and what
 * it frees on a tier change, a change of the map's shape, a context lost before
 * or during the build and a dust nest that changes under it. The GL classes are
 * fakes that count what they hold, so a leak shows as a number.
 */

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import { PerspectiveCamera, Scene, type WebGLRenderer } from 'three';
import type { StarDust } from '$lib/scene/dust/star-dust';
import type { Vec3 } from '$lib/scene/dust/octahedral';
import { ADAPT_REST_MS } from './exposure';
import { GLOW_CUT_MAG, GlowSky, type GlowFrame, type GlowPlan } from './glow-sky';

const gl = vi.hoisted(() => ({
	live: new Set<object>(),
	runs: [] as {
		origin: Vec3;
		from: number;
		rows: number;
		cut: number;
		weight: number;
		galaxy: boolean;
		alone: boolean;
	}[],
	shown: 0,
	uploadFrames: 2,
	measured: [] as boolean[],
	/** Steps of the eye: true for one that takes its target at once. */
	steps: [] as boolean[],
	/** Questions to the eye, and what the GPU answers: null while it has no answer. */
	asks: 0,
	close: null as boolean | null,
	/** Questions on the model's share, and the answer. */
	shareAsks: [] as number[],
	modelShare: null as boolean | null,
	/** A question on the share is out. */
	sharePending: false,
	/** The edge of the map about the Galaxy that each march was built for. */
	galaxyEdges: [] as number[],
	/** The blend of each frame shown. */
	blends: [] as number[],
	/** The share each composite showed, by the order they were made in. */
	composites: [] as number[][],
	/** The share the far regions showed, and the parts each march was built for. */
	regions: [] as number[],
	parts: [] as unknown[],
	marches: 0,
	failMarch: false,
	/** Volumes made, and the one whose constructor throws, counted from 1. */
	volumes: 0,
	failVolumeAt: 0,
	lost: false
}));

const net = vi.hoisted(() => ({
	metadata: null as (() => Promise<unknown>) | null,
	volumes: 0,
	emission: false,
	/** More of the glow's data, as the model. */
	extra: {} as Record<string, unknown>
}));

vi.mock('$lib/scene/dust/march', () => ({
	VolumeTextures: class {
		steps = 0;
		readonly volume = true;
		constructor() {
			if (++gl.volumes === gl.failVolumeAt) throw new Error('glow: out of memory');
			gl.live.add(this);
		}
		get uploaded() {
			return this.steps >= gl.uploadFrames;
		}
		step() {
			this.steps++;
		}
		dispose() {
			gl.live.delete(this);
		}
	},
	SkyMap: class {
		external = {};
		constructor() {
			gl.live.add(this);
		}
		dispose() {
			gl.live.delete(this);
		}
	}
}));

vi.mock('./march', () => ({
	GlowMarch: class {
		constructor(...args: unknown[]) {
			// On a lost context the march does not link.
			if (gl.failMarch) throw new Error('dust march: link failed');
			gl.marches++;
			gl.galaxyEdges.push((args[7] as GlowPlan).galaxy);
			const emission = args[9] as { parts: { halpha: boolean; scatter: boolean } } | null;
			gl.parts.push(emission?.parts ?? null);
			this.emissionAlone = !!emission && (emission.parts.halpha || emission.parts.scatter);
			gl.live.add(this);
		}
		emissionAlone = false;
		run(
			_map: unknown,
			origin: Vec3,
			cut: number,
			_jitter: number,
			weight: number,
			from: number,
			rows: number,
			frame: unknown,
			alone = false
		) {
			gl.runs.push({ origin, from, rows, cut, weight, galaxy: frame !== null, alone });
		}
		dispose() {
			gl.live.delete(this);
		}
	}
}));

vi.mock('./eye', () => ({
	GlowEye: class {
		texture = {};
		constructor() {
			gl.live.add(this);
		}
		measure(_map: unknown, reference: boolean) {
			gl.measured.push(reference);
		}
		step(_dtMs: number, atOnce: boolean) {
			gl.steps.push(atOnce);
		}
		ask() {
			gl.asks++;
		}
		answer() {
			return gl.asks > 0 ? gl.close : null;
		}
		askShare(share: number) {
			gl.shareAsks.push(share);
		}
		shareAnswer() {
			return gl.shareAsks.length > 0 ? gl.modelShare : null;
		}
		get sharePending() {
			return gl.sharePending;
		}
		dispose() {
			gl.live.delete(this);
		}
	}
}));

vi.mock('./composite', () => ({
	GlowComposite: class {
		private readonly shares: number[] = [];
		constructor() {
			gl.live.add(this);
			gl.composites.push(this.shares);
		}
		show(
			_map: unknown,
			_previous: unknown,
			blend: number,
			_gain: unknown,
			_exposure: number,
			share: number
		) {
			gl.shown++;
			gl.blends.push(blend);
			this.shares.push(share);
		}
		hide() {}
		dispose() {
			gl.live.delete(this);
		}
	}
}));

vi.mock('./emission', async (importActual) => ({
	...(await importActual<typeof import('./emission')>()),
	EmissionTextures: class {
		constructor() {
			gl.live.add(this);
		}
		get uploaded() {
			return true;
		}
		step() {}
		dispose() {
			gl.live.delete(this);
		}
	}
}));

vi.mock('./regions', () => ({
	GlowRegions: class {
		constructor() {
			gl.live.add(this);
		}
		show(...args: unknown[]) {
			gl.regions.push(args[4] as number);
		}
		hide() {}
		dispose() {
			gl.live.delete(this);
		}
	}
}));

vi.mock('./grid', async (importActual) => ({
	...(await importActual<typeof import('./grid')>()),
	fetchGlowMetadata: () => net.metadata!(),
	fetchGlowVolume: async () => {
		net.volumes++;
		return {
			entry: { size: 2, shells: 2 },
			a: new Uint16Array(32),
			b: new Uint16Array(32),
			emission: net.emission
				? { halpha: {}, scatter: {}, regions: { light: new Float32Array(3) } }
				: null,
			...net.extra
		};
	}
}));

const TREE = 'tree-token';
const NEST = 'nest-token';
const META = {
	format: 1,
	token: 'abc',
	inputs: { tree: TREE, dust: NEST },
	distribution: 'open',
	tiers: { high: {}, low: {} }
};
const PLAN: GlowPlan = { grid: 'high', size: 64, steps: 8, passes: 2, galaxy: 0 };

let clock = 0;
let canvas: EventTarget;
let warn: MockInstance;
/** The dust's refresh found the same reach everywhere: 0.05 pc. */
let dust: {
	marchNest: object | null;
	reachAtSun: number;
	latestReach: number;
	frame: unknown;
	token: string | null;
	columns: unknown;
};

function make(plan: GlowPlan | null = PLAN): GlowSky {
	canvas = new EventTarget();
	const renderer = { domElement: canvas, getContext: () => ({ isContextLost: () => gl.lost }) };
	return new GlowSky(
		renderer as unknown as WebGLRenderer,
		new Scene(),
		plan,
		dust as unknown as StarDust,
		() => {}
	);
}

const camera = new PerspectiveCamera();

function frame(at: Vec3, extra: Partial<GlowFrame> = {}): GlowFrame {
	clock += 16;
	return {
		camera,
		tree: TREE,
		at,
		treeToScene: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
		treeScale: 1,
		active: true,
		drawing: true,
		share: 1,
		skybox: 0,
		heightPx: 900,
		nowMs: clock,
		dtMs: 16,
		...extra
	};
}

async function ready(glow: GlowSky, at: Vec3 = [0, 0, 0]) {
	for (let i = 0; i < 20 && glow.stats().phase !== 'ready'; i++) {
		glow.update(frame(at));
		await vi.advanceTimersByTimeAsync(0);
	}
	expect(glow.stats().phase).toBe('ready');
}

function settle(glow: GlowSky, at: Vec3, extra: Partial<GlowFrame> = {}): void {
	for (let i = 0; i < 1000; i++) {
		glow.update(frame(at, extra));
		if (!glow.busy()) break;
	}
	expect(glow.busy()).toBe(false);
}

beforeEach(() => {
	vi.useFakeTimers();
	clock = 0;
	gl.live.clear();
	gl.runs = [];
	gl.shown = 0;
	gl.measured = [];
	gl.steps = [];
	gl.asks = 0;
	gl.close = null;
	gl.shareAsks = [];
	gl.modelShare = null;
	gl.sharePending = false;
	gl.galaxyEdges = [];
	gl.blends = [];
	gl.composites = [];
	gl.regions = [];
	gl.parts = [];
	gl.marches = 0;
	gl.failMarch = false;
	gl.volumes = 0;
	gl.failVolumeAt = 0;
	gl.lost = false;
	net.metadata = async () => META;
	net.volumes = 0;
	net.emission = false;
	net.extra = {};
	dust = {
		marchNest: {},
		reachAtSun: 0.05,
		latestReach: 0.05,
		frame: {
			rotation_to_icrs: [
				[1, 0, 0],
				[0, 1, 0],
				[0, 0, 1]
			]
		},
		token: NEST,
		columns: { map: {}, origin: [0, 0, 0] }
	};
	warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => {
	vi.useRealTimers();
	vi.restoreAllMocks();
});

describe('loading', () => {
	it('waits for the dust’s GPU nest, then builds a march, three maps, a meter and the composite', async () => {
		dust.marchNest = null;
		const glow = make();
		for (let i = 0; i < 5; i++) glow.update(frame([0, 0, 0]));
		await vi.advanceTimersByTimeAsync(0);
		expect(glow.stats().phase).toBe('idle');
		dust.marchNest = {};
		await ready(glow);
		expect(gl.live.size).toBe(7);
		expect(net.volumes).toBe(1);
	});

	it('loads nothing before the prefetch distance', async () => {
		const glow = make();
		for (let i = 0; i < 5; i++) glow.update(frame([0, 0, 0], { active: false }));
		await vi.advanceTimersByTimeAsync(0);
		expect(glow.stats().phase).toBe('idle');
		expect(net.volumes).toBe(0);
	});

	it('draws nothing, and is not busy, where the host has no grid', async () => {
		net.metadata = async () => null;
		const glow = make();
		glow.update(frame([0, 0, 0]));
		await vi.advanceTimersByTimeAsync(0);
		expect(glow.stats().phase).toBe('none');
		glow.update(frame([0, 0, 0]));
		expect(glow.busy()).toBe(false);
		expect(gl.live.size).toBe(0);
	});

	it('has no plan on the low tier', async () => {
		const glow = make(null);
		glow.update(frame([0, 0, 0]));
		await vi.advanceTimersByTimeAsync(0);
		expect(glow.stats().phase).toBe('idle');
		expect(glow.busy()).toBe(false);
	});
});

describe('a load whose textures fail', () => {
	it('frees the grid when the model does not upload, so the retry holds one grid', async () => {
		const box = { size: [2, 2, 2], data: new Uint16Array(8) };
		net.extra = { model: { inner: box, outer: box } };
		gl.failVolumeAt = 2;
		const volumes = () => [...gl.live].filter((o) => 'volume' in o).length;
		const glow = make();
		glow.update(frame([0, 0, 0]));
		await vi.advanceTimersByTimeAsync(0);
		expect(glow.stats().phase).toBe('idle');
		expect(volumes()).toBe(0);
		await vi.advanceTimersByTimeAsync(5_000);
		await ready(glow);
		expect(net.volumes).toBe(2);
		expect(volumes()).toBe(2);
	});
});

describe('maps', () => {
	it('makes the first map at the Sun in the solar system, then rests', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, [0, 0, 0], { drawing: false });
		const rows = gl.runs.reduce((sum, run) => sum + run.rows, 0);
		expect(rows).toBe(PLAN.size * PLAN.passes);
		expect(gl.runs[0].weight).toBe(1);
		expect(glow.stats().refreshes).toBe(1);
		const before = gl.runs.length;
		settle(glow, [0, 0, 0]);
		expect(gl.runs.length).toBe(before);
		expect(gl.shown).toBeGreaterThan(0);
	});

	it('makes a new map only when the camera leaves the reach', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, [0, 0, 0]);
		settle(glow, [0.04, 0, 0]);
		expect(glow.stats().refreshes).toBe(1);
		settle(glow, [0.2, 0, 0]);
		expect(glow.stats().refreshes).toBe(2);
	});

	it('cuts every map at the skybox’s limit, from any place', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, [0, 0, 0]);
		settle(glow, [5000, 0, 0]);
		expect(glow.stats().refreshes).toBe(2);
		expect(gl.runs.every((run) => run.cut === GLOW_CUT_MAG)).toBe(true);
		expect(GLOW_CUT_MAG).toBe(7.5);
	});

	it('makes the map at the Sun first and does not show it, when the camera starts far away', async () => {
		const glow = make();
		await ready(glow, [50, 0, 0]);
		settle(glow, [50, 0, 0]);
		const sun = gl.runs.filter((run) => run.origin.every((x) => x === 0));
		expect(sun.reduce((sum, run) => sum + run.rows, 0)).toBe(PLAN.size * PLAN.passes);
		expect(gl.runs[0].origin).toEqual([0, 0, 0]);
		expect(glow.stats().refreshes).toBe(1);
		expect(glow.stats().origin).toEqual([50, 0, 0]);
	});

	it('blends a new map in over a few frames, and rests after', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, [0, 0, 0]);
		let swapped = false;
		for (let i = 0; i < 200 && !swapped; i++) {
			glow.update(frame([0.2, 0, 0]));
			swapped = glow.stats().refreshes === 2;
		}
		expect(swapped).toBe(true);
		expect(glow.busy()).toBe(true);
		settle(glow, [0.2, 0, 0]);
	});

	it('holds a finished map until the blend before it ends, so no map drops at once', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, [0, 0, 0]);
		gl.blends = [];
		// The camera leaves each map's reach in every frame.
		for (let i = 1; i <= 200; i++) glow.update(frame([0.2 * i, 0, 0]));
		const restarts = gl.blends.filter((blend, i) => i > 0 && blend < gl.blends[i - 1]);
		expect(restarts.length).toBeGreaterThan(5);
		gl.blends.forEach((blend, i) => {
			if (i > 0 && blend < gl.blends[i - 1]) expect(gl.blends[i - 1]).toBe(1);
		});
	});

	it('takes the reach the dust found for its own refresh', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, [0, 0, 0]);
		expect(glow.stats().reach).toBe(0.05);
		dust.latestReach = 1;
		settle(glow, [0.2, 0, 0]);
		expect(glow.stats().refreshes).toBe(2);
		expect(glow.stats().reach).toBe(1);
		settle(glow, [0.9, 0, 0]);
		expect(glow.stats().refreshes).toBe(2);
		settle(glow, [1.5, 0, 0]);
		expect(glow.stats().refreshes).toBe(3);
	});

	it('does not march while the stars do not draw, once a map is made', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, [0, 0, 0]);
		const before = gl.runs.length;
		settle(glow, [5, 0, 0], { drawing: false });
		expect(gl.runs.length).toBe(before);
	});

	it('makes maps less often while frames are slow, as the dust does', async () => {
		/** Maps made while the camera leaves each map's reach in every frame. */
		const maps = async (dtMs: number) => {
			const glow = make();
			await ready(glow);
			settle(glow, [0, 0, 0]);
			for (let i = 1; i <= 300; i++) glow.update(frame([0.2 * i, 0, 0], { dtMs }));
			return glow.stats().refreshes;
		};
		const fast = await maps(16);
		const slow = await maps(60);
		expect(slow).toBeGreaterThan(1);
		expect(slow * 3).toBeLessThan(fast);
	});
});

describe('turned off', () => {
	it('drops the map at the Sun it was making, rests, and makes it again when on', async () => {
		const glow = make();
		await ready(glow, [50, 0, 0]);
		glow.update(frame([50, 0, 0]));
		expect(gl.runs.length).toBeGreaterThan(0);
		glow.setEnabled(false);
		glow.update(frame([50, 0, 0]));
		expect(glow.busy()).toBe(false);
		const before = gl.runs.length;
		settle(glow, [50, 0, 0]);
		expect(gl.runs.length).toBe(before);
		glow.setEnabled(true);
		settle(glow, [50, 0, 0]);
		const again = gl.runs.slice(before);
		const sun = again.filter((run) => run.origin.every((x) => x === 0));
		expect(again[0]).toMatchObject({ origin: [0, 0, 0], from: 0, weight: 1 });
		expect(sun.reduce((sum, run) => sum + run.rows, 0)).toBe(PLAN.size * PLAN.passes);
		expect(gl.measured).toEqual([true, false]);
		expect(gl.shown).toBeGreaterThan(0);
	});

	it('rests between the map at the Sun and the first map of the camera', async () => {
		const glow = make();
		await ready(glow, [50, 0, 0]);
		for (let i = 0; i < 100 && gl.measured.length === 0; i++) glow.update(frame([50, 0, 0]));
		expect(gl.measured).toEqual([true]);
		glow.setEnabled(false);
		glow.update(frame([50, 0, 0]));
		expect(glow.busy()).toBe(false);
		glow.setEnabled(true);
		settle(glow, [50, 0, 0]);
		expect(gl.measured).toEqual([true, false]);
		expect(gl.shown).toBeGreaterThan(0);
	});
});

describe('exposure', () => {
	it('measures the map at the Sun as the reference and as the first map, and shows nothing before', async () => {
		const glow = make();
		await ready(glow);
		for (let i = 0; i < 50 && gl.measured.length === 0; i++) {
			glow.update(frame([0, 0, 0]));
			if (gl.measured.length === 0) expect(gl.shown).toBe(0);
		}
		expect(gl.measured).toEqual([true, false]);
		settle(glow, [0, 0, 0]);
		expect(gl.shown).toBeGreaterThan(0);
		// The first mean is taken at once.
		expect(gl.steps[0]).toBe(true);
	});

	it('measures each map that takes over', async () => {
		const glow = make();
		await ready(glow, [50, 0, 0]);
		settle(glow, [50, 0, 0]);
		expect(gl.measured).toEqual([true, false]);
		settle(glow, [50.5, 0, 0]);
		expect(gl.measured).toEqual([true, false, false]);
	});

	/** Frames from the camera's move to the end of the eye's work, and its steps. */
	async function adaptAfterMove(): Promise<boolean[]> {
		const glow = make();
		await ready(glow);
		settle(glow, [0, 0, 0]);
		gl.steps = [];
		gl.asks = 0;
		for (let frames = 0; frames < 2000; frames++) {
			glow.update(frame([0.2, 0, 0]));
			if (glow.stats().refreshes === 2 && !glow.busy()) break;
		}
		expect(glow.busy()).toBe(false);
		const steps = gl.steps.slice();
		settle(glow, [0.2, 0, 0]);
		expect(gl.steps.length).toBe(steps.length);
		return steps;
	}

	it('eases to a new mean while the glow shows, then takes its target at the end of the time of rest', async () => {
		const steps = await adaptAfterMove();
		expect(steps.slice(0, -1).every((atOnce) => !atOnce)).toBe(true);
		expect(steps.at(-1)).toBe(true);
		expect(steps.length * 16).toBeGreaterThanOrEqual(ADAPT_REST_MS - 32);
		expect(steps.length * 16).toBeLessThanOrEqual(ADAPT_REST_MS + 32);
		expect(gl.asks).toBeGreaterThan(0);
	});

	it('stops and takes its target as soon as the GPU finds it close', async () => {
		gl.close = true;
		const steps = await adaptAfterMove();
		expect(steps).toEqual([false, true]);
	});

	it('goes on easing while the GPU finds it far', async () => {
		gl.close = false;
		const steps = await adaptAfterMove();
		expect(steps.length * 16).toBeGreaterThanOrEqual(ADAPT_REST_MS - 32);
	});

	it('takes a new mean at once while the glow does not show', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, [0, 0, 0]);
		gl.steps = [];
		settle(glow, [0.2, 0, 0], { share: 0 });
		expect(gl.steps).toEqual([true]);
	});
});

describe('plan changes', () => {
	it('frees the old objects on a tier change, and builds the new plan', async () => {
		const glow = make();
		await ready(glow);
		glow.setPlan({ ...PLAN, grid: 'low', size: 32 });
		expect(gl.live.size).toBe(0);
		await ready(glow);
		expect(gl.live.size).toBe(7);
		glow.setPlan(null);
		expect(gl.live.size).toBe(0);
		glow.update(frame([0, 0, 0]));
		expect(glow.busy()).toBe(false);
	});

	it('keeps the grid on a change of size, steps or passes, and builds the rest again', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, [0, 0, 0]);
		const before = new Set(gl.live);
		gl.runs = [];
		const plan = { ...PLAN, size: 32, steps: 16, passes: 4 };
		glow.setPlan(plan);
		expect(glow.stats().phase).toBe('uploading');
		await ready(glow);
		expect(gl.live.size).toBe(7);
		expect([...gl.live].filter((object) => before.has(object))).toHaveLength(1);
		expect(net.volumes).toBe(1);
		expect(gl.marches).toBe(2);
		settle(glow, [0, 0, 0]);
		expect(gl.runs.reduce((sum, run) => sum + run.rows, 0)).toBe(plan.size * plan.passes);
		expect(gl.measured.filter((reference) => reference)).toHaveLength(2);
	});

	it('loads again on a change of shape while the context is lost', async () => {
		const glow = make();
		await ready(glow);
		gl.lost = true;
		glow.setPlan({ ...PLAN, size: 32 });
		expect(glow.stats().phase).toBe('idle');
	});

	it('keeps the grid when the dust’s nest changes under it, and builds the rest again', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, [0, 0, 0]);
		const before = new Set(gl.live);
		dust.marchNest = {};
		glow.update(frame([0, 0, 0]));
		await ready(glow);
		expect(gl.live.size).toBe(7);
		// Only the grid is from before, and it was not asked for again.
		expect([...gl.live].filter((object) => before.has(object))).toHaveLength(1);
		expect(net.volumes).toBe(1);
		expect(gl.marches).toBe(2);
		settle(glow, [0, 0, 0]);
		expect(gl.measured.filter((reference) => reference)).toHaveLength(2);
	});

	it('waits with the grid while the dust has no nest on the GPU', async () => {
		const glow = make();
		await ready(glow);
		dust.marchNest = null;
		glow.update(frame([0, 0, 0]));
		expect(gl.live.size).toBe(1);
		expect(glow.busy()).toBe(false);
		dust.marchNest = {};
		await ready(glow);
		expect(net.volumes).toBe(1);
	});

	it('loads again after a lost context, with nothing of the old one to free', async () => {
		const glow = make();
		await ready(glow);
		// The lost context took these; a fake keeps them.
		const lost = new Set(gl.live);
		canvas.dispatchEvent(new Event('webglcontextrestored'));
		expect(glow.stats().phase).toBe('idle');
		await ready(glow);
		glow.dispose();
		expect([...gl.live].every((object) => lost.has(object))).toBe(true);
		expect(gl.live.size).toBe(6);
	});

	it('is no failure of the device during the build: the restore builds the glow', async () => {
		const glow = make();
		for (let i = 0; i < 20 && glow.stats().phase !== 'uploading'; i++) {
			glow.update(frame([0, 0, 0]));
			await vi.advanceTimersByTimeAsync(0);
		}
		gl.lost = true;
		gl.failMarch = true;
		for (let i = 0; i < 5; i++) glow.update(frame([0, 0, 0]));
		await vi.advanceTimersByTimeAsync(0);
		expect(glow.stats().phase).toBe('idle');
		expect(glow.busy()).toBe(false);
		// Nothing loads on the lost context.
		expect(net.volumes).toBe(1);
		gl.lost = false;
		gl.failMarch = false;
		canvas.dispatchEvent(new Event('webglcontextrestored'));
		await ready(glow);
		expect(net.volumes).toBe(2);
		expect(warn).not.toHaveBeenCalled();
	});
});

describe('the inputs of the grid', () => {
	const stale = () =>
		warn.mock.calls.filter((call) => String(call[0]).includes('the grid is of')).length;

	it('draw with no warning when they are the tree and the nest that draw', async () => {
		const glow = make();
		await ready(glow);
		expect(stale()).toBe(0);
	});

	it('still draw from another tree or nest, with one warning a session', async () => {
		dust.token = 'another-nest';
		const glow = make();
		await ready(glow);
		settle(glow, [0, 0, 0]);
		expect(gl.shown).toBeGreaterThan(0);
		expect(stale()).toBe(1);
		glow.setPlan({ ...PLAN, grid: 'low', size: 32 });
		await ready(glow);
		expect(stale()).toBe(1);
	});
});

describe('outside the Galaxy', () => {
	const CENTRE: Vec3 = [8_277, 0, -21];
	const withModel = () => {
		net.metadata = async () => ({ ...META, model: { centre_pc: CENTRE } });
	};
	const OUTSIDE: Vec3 = [8_277, 30_000, -21];

	it('marches no map about the Galaxy inside it, nor on a host with no model', async () => {
		withModel();
		const glow = make({ ...PLAN, galaxy: 32 });
		await ready(glow);
		settle(glow, [0, 0, 0]);
		expect(gl.runs.some((run) => run.galaxy)).toBe(false);
		net.metadata = async () => META;
		const bare = make({ ...PLAN, galaxy: 32 });
		await ready(bare, OUTSIDE);
		settle(bare, OUTSIDE);
		expect(gl.runs.some((run) => run.galaxy)).toBe(false);
	});

	it('makes the maps about the Galaxy and their march only with a model', async () => {
		withModel();
		await ready(make({ ...PLAN, galaxy: 32 }));
		// The grid, the march, three sky maps, three maps about the Galaxy, the eye and the composite.
		expect(gl.live.size).toBe(10);
		net.metadata = async () => META;
		const before = gl.live.size;
		await ready(make({ ...PLAN, galaxy: 32 }));
		expect(gl.live.size - before).toBe(7);
		expect(gl.galaxyEdges).toEqual([32, 0]);
	});

	it('marches the sky map and the map about the Galaxy in each pass, far outside', async () => {
		withModel();
		const glow = make({ ...PLAN, galaxy: 32 });
		await ready(glow, OUTSIDE);
		settle(glow, OUTSIDE);
		const far = gl.runs.filter((run) => run.origin[1] > 0);
		const sky = far.filter((run) => !run.galaxy).reduce((sum, run) => sum + run.rows, 0);
		const galaxy = far.filter((run) => run.galaxy).reduce((sum, run) => sum + run.rows, 0);
		expect(sky).toBe(PLAN.size * PLAN.passes);
		expect(galaxy).toBe(32 * PLAN.passes);
		expect(glow.stats().galaxy?.share).toBe(1);
		expect(glow.busy()).toBe(false);
	});

	it('says the view is model once the GPU finds the model holds a share of a map, with two thresholds', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, [0, 0, 0]);
		expect(glow.modelInView).toBe(false);
		expect(gl.shareAsks.at(-1)).toBeGreaterThan(0);
		gl.modelShare = true;
		settle(glow, [0, 0, 0]);
		expect(glow.modelInView).toBe(true);
		glow.update(frame([0, 0, 0], { drawing: false, share: 0 }));
		expect(glow.modelInView).toBe(false);
	});

	it('stays awake while the question on the model’s share is out', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, [0, 0, 0]);
		gl.sharePending = true;
		glow.update(frame([0, 0, 0]));
		expect(glow.busy()).toBe(true);
		gl.sharePending = false;
		glow.update(frame([0, 0, 0]));
		expect(glow.busy()).toBe(false);
	});
});

describe('light that is not starlight', () => {
	const withEmission = () => {
		net.emission = true;
		net.metadata = async () => ({ ...META, emission: {} });
	};
	const NEAR_SUN: Vec3 = [0.005, 0, 0];

	it('makes the map of the emission alone at the Sun with the first map, and no other', async () => {
		withEmission();
		const glow = make();
		await ready(glow);
		settle(glow, [0, 0, 0]);
		const alone = gl.runs.filter((run) => run.alone);
		expect(alone.length).toBeGreaterThan(0);
		expect(alone.every((run) => run.origin.every((x) => x === 0))).toBe(true);
		// Each pass marches the sky map, then the emission alone: 2 passes of 64 rows.
		expect(alone.reduce((n, run) => n + run.rows, 0)).toBe(2 * 64);
		const before = gl.runs.length;
		settle(glow, [5, 0, 0]);
		expect(gl.runs.slice(before).some((run) => run.alone)).toBe(false);
		expect(glow.stats().emission?.sunMap).toBe(true);
	});

	it('draws the emission alone over the skybox inside the solar system, and the far regions on both sides', async () => {
		withEmission();
		const glow = make();
		await ready(glow);
		settle(glow, NEAR_SUN, { drawing: false, share: 0, skybox: 0.8 });
		const [outside, inside] = gl.composites;
		expect(outside.length).toBe(0);
		expect(inside.at(-1)).toBeCloseTo(0.8, 6);
		expect(gl.regions.at(-1)).toBeCloseTo(0.8, 6);
		settle(glow, NEAR_SUN, { skybox: 0 });
		expect(outside.at(-1)).toBe(1);
		expect(gl.regions.at(-1)).toBe(1);
	});

	it('draws nothing of it with the glow off, once the fade ends', async () => {
		withEmission();
		const glow = make();
		await ready(glow);
		const inSky = { drawing: false, share: 0, skybox: 1 };
		settle(glow, NEAR_SUN, inSky);
		glow.setEnabled(false);
		settle(glow, NEAR_SUN, inSky);
		const [, inside] = gl.composites;
		const shown = inside.length;
		const regions = gl.regions.length;
		for (let i = 0; i < 5; i++) glow.update(frame(NEAR_SUN, inSky));
		expect(inside.length).toBe(shown);
		expect(gl.regions.length).toBe(regions);
	});

	it('turns off for the gates: the maps are made again as on a host with none', async () => {
		withEmission();
		const glow = make();
		await ready(glow);
		settle(glow, [0, 0, 0]);
		glow.setEmission({ halpha: false, scatter: false, regions: false });
		gl.runs = [];
		settle(glow, NEAR_SUN, { skybox: 0 });
		expect(gl.parts.at(-1)).toEqual({ halpha: false, scatter: false, regions: false });
		expect(gl.runs.some((run) => run.alone)).toBe(false);
		// The march, three maps, the eye, the composite, no map of the emission alone
		// and no regions; the grid and the emission's textures stay.
		expect(gl.live.size).toBe(8);
		glow.setEmission({ halpha: true, scatter: true, regions: true });
		settle(glow, NEAR_SUN, { skybox: 0 });
		expect(gl.live.size).toBe(11);
	});

	it('loads none of it, and draws as before, on a host with none', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, NEAR_SUN, { drawing: false, share: 0, skybox: 1 });
		expect(gl.composites.length).toBe(1);
		expect(gl.regions.length).toBe(0);
		expect(glow.stats().emission).toBeNull();
	});
});
