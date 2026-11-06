/**
 * The life of `GlowSky`: when it loads, when it marches, when it rests, when it
 * steps down on a slow device, and what it frees on a tier change, a change of
 * the plan's shape, a context lost before or during the build, a target that
 * fails and a dust nest that changes under it. The GL classes are fakes that
 * count what they hold, so a leak shows as a number.
 */

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import {
	CubeTexture,
	Euler,
	PerspectiveCamera,
	Scene,
	type Vector2,
	type WebGLRenderer
} from 'three';
import type { StarDust } from '$lib/scene/dust/star-dust';
import type { Vec3 } from '$lib/scene/dust/octahedral';
import { GLOW_CUT_MAG } from '$lib/scene/starfield/band';
import { SUN_EXPOSURE, joinShare, placeGain } from './exposure';
import { GlowSky, stepDown, type GlowFrame, type GlowPlan, type SkyboxSource } from './glow-sky';
import { StarlessSky } from './starless';

const gl = vi.hoisted(() => ({
	live: new Set<object>(),
	runs: [] as {
		origin: Vec3;
		cut: number;
		jitter: number;
		weight: number;
		/** The screen target, or the map of the emission alone. */
		screen: boolean;
		size: [number, number];
		/** Where in its texel the ray goes. */
		offset: number[] | null;
	}[],
	uploadFrames: 2,
	/** What each composite showed, by the order they were made in. */
	composites: [] as { share: number; exposure: number; map: unknown; lod: number }[][],
	/** The share the far regions showed, and the parts each march was built for. */
	regions: [] as number[],
	parts: [] as unknown[],
	/** The steps each march was built for. */
	steps: [] as unknown[],
	marches: 0,
	failMarch: false,
	/** Volumes made, and the one whose constructor throws, counted from 1. */
	volumes: 0,
	failVolumeAt: 0,
	/** A screen target fails to be made. */
	failTarget: false,
	lost: false,
	/** The view in CSS pixels, and the pixel ratio. */
	size: [1600, 900] as [number, number],
	pixelRatio: 1
}));

const net = vi.hoisted(() => ({
	metadata: null as (() => Promise<unknown>) | null,
	volumes: 0,
	emission: false,
	/** More of the glow's data, as the model. */
	extra: {} as Record<string, unknown>
}));

vi.mock('$lib/scene/dust/march', () => {
	class FloatTarget {
		external = {};
		constructor(
			_renderer: unknown,
			readonly width: number,
			readonly height: number
		) {
			if (gl.failTarget) throw new Error('float target: framebuffer 36054');
			gl.live.add(this);
		}
		dispose() {
			gl.live.delete(this);
		}
	}
	return {
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
		FloatTarget,
		SkyMap: class extends FloatTarget {
			constructor(renderer: unknown, size: number) {
				super(renderer, size, size);
			}
		}
	};
});

vi.mock('./march', async (importActual) => ({
	...(await importActual<typeof import('./march')>()),
	GlowMarch: class {
		constructor(...args: unknown[]) {
			// On a lost context the march does not link.
			if (gl.failMarch) throw new Error('dust march: link failed');
			gl.marches++;
			gl.steps.push(args[7]);
			const emission = args[10] as { parts: { halpha: boolean; scatter: boolean } } | null;
			gl.parts.push(emission?.parts ?? null);
			this.emissionAlone = !!emission && (emission.parts.halpha || emission.parts.scatter);
			gl.live.add(this);
		}
		emissionAlone = false;
		run(
			target: { width: number; height: number },
			origin: Vec3,
			cut: number,
			jitter: number,
			weight: number,
			view: { offset: readonly number[] } | null
		) {
			gl.runs.push({
				origin: [...origin] as Vec3,
				cut,
				jitter,
				weight,
				screen: view !== null,
				size: [target.width, target.height],
				offset: view ? [...view.offset] : null
			});
		}
		dispose() {
			gl.live.delete(this);
		}
	}
}));

vi.mock('./composite', async (importActual) => ({
	...(await importActual<typeof import('./composite')>()),
	GlowComposite: class {
		private readonly shown: { share: number; exposure: number; map: unknown; lod: number }[] = [];
		constructor() {
			gl.live.add(this);
			gl.composites.push(this.shown);
		}
		show(map: unknown, exposure: number, share: number, lod = 0) {
			this.shown.push({ share, exposure, map, lod });
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
			gl.regions.push(args[3] as number);
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
const PLAN: GlowPlan = { grid: 'high', divisor: 2, steps: 32, passes: 4, sunSize: 64 };
/** The finest cell of the fake nest is 2 pc. */
const nest = () => ({ levels: [{ half: [250, 250, 250], size: [250, 250, 250] }] });
const CENTRE: Vec3 = [8_277, 0, -21];
/** Past the join, where the stars draw. */
const OUT: Vec3 = [100, 0, 10];

let clock = 0;
let canvas: EventTarget;
let warn: MockInstance;
let dust: {
	marchNest: object | null;
	frame: unknown;
	token: string | null;
	columns: unknown;
};

/** A skybox the glow reads past the join. */
const SKYBOX = (): SkyboxSource => ({
	texture: new CubeTexture(),
	rotation: new Euler(),
	faceTexels: 4096
});

function make(
	plan: GlowPlan | null = PLAN,
	skybox?: () => SkyboxSource | null,
	starless?: StarlessSky
): GlowSky {
	canvas = new EventTarget();
	const renderer = {
		domElement: canvas,
		getContext: () => ({ isContextLost: () => gl.lost }),
		getSize: (v: Vector2) => v.set(...gl.size),
		getDrawingBufferSize: (v: Vector2) =>
			v.set(gl.size[0] * gl.pixelRatio, gl.size[1] * gl.pixelRatio)
	};
	return new GlowSky(
		renderer as unknown as WebGLRenderer,
		new Scene(),
		plan,
		dust as unknown as StarDust,
		() => {},
		skybox,
		starless
	);
}

const camera = new PerspectiveCamera(60, 16 / 9, 0.1, 10);

/** Turn the camera by `yaw` radians: a new pose with the same place. */
function turn(yaw: number): void {
	camera.rotation.set(0, yaw, 0);
	camera.updateMatrixWorld();
}

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
		skyboxLayer: false,
		nowMs: clock,
		dtMs: 16,
		...extra
	};
}

async function ready(glow: GlowSky, at: Vec3 = [0, 0, 0]) {
	for (let i = 0; i < 20 && glow.stats().phase !== 'ready'; i++) {
		glow.update(frame(at, { drawing: false, share: 0 }));
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

const screenRuns = () => gl.runs.filter((run) => run.screen);

beforeEach(() => {
	vi.useFakeTimers();
	clock = 0;
	turn(0);
	gl.live.clear();
	gl.runs = [];
	gl.composites = [];
	gl.regions = [];
	gl.parts = [];
	gl.steps = [];
	gl.marches = 0;
	gl.failMarch = false;
	gl.volumes = 0;
	gl.failVolumeAt = 0;
	gl.failTarget = false;
	gl.lost = false;
	gl.size = [1600, 900];
	gl.pixelRatio = 1;
	net.metadata = async () => META;
	net.volumes = 0;
	net.emission = false;
	net.extra = {};
	dust = {
		marchNest: nest(),
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
	it('waits for the dust’s GPU nest, then builds a march and the composite', async () => {
		dust.marchNest = null;
		const glow = make();
		for (let i = 0; i < 5; i++) glow.update(frame([0, 0, 0]));
		await vi.advanceTimersByTimeAsync(0);
		expect(glow.stats().phase).toBe('idle');
		dust.marchNest = nest();
		await ready(glow);
		// The grid, the march and the composites of the march and the skybox; the
		// screen target comes with the first pose.
		expect(gl.live.size).toBe(4);
		expect(net.volumes).toBe(1);
		expect(gl.steps).toEqual([{ screen: PLAN.steps, sky: 48 }]);
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

describe('the march from the camera', () => {
	it('marches the screen from the camera in the frame that shows it, into a part of the buffer', async () => {
		const glow = make();
		await ready(glow);
		glow.update(frame(OUT));
		expect(screenRuns()).toHaveLength(1);
		const [run] = screenRuns();
		expect(run.origin).toEqual(OUT);
		expect(run.weight).toBe(1);
		expect(run.size).toEqual([800, 450]);
		expect(gl.composites[0].at(-1)?.share).toBeGreaterThan(0);
	});

	it('marches pass 0 alone in each frame of a flight, from that frame’s place', async () => {
		const glow = make();
		await ready(glow);
		const path: Vec3[] = Array.from({ length: 20 }, (_, i) => [100 + i, 0, 10]);
		for (const at of path) glow.update(frame(at));
		const runs = screenRuns();
		expect(runs.map((run) => run.origin)).toEqual(path);
		expect(runs.every((run) => run.weight === 1 && run.jitter === runs[0].jitter)).toBe(true);
	});

	it('marches again when the view turns, with no change of place', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, OUT);
		const before = screenRuns().length;
		turn(0.1);
		glow.update(frame(OUT));
		expect(screenRuns()).toHaveLength(before + 1);
		expect(screenRuns().at(-1)?.weight).toBe(1);
	});

	it('blends in the rest of the passes at rest, one a frame, and then does no work', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, OUT);
		const runs = screenRuns();
		expect(runs.map((run) => run.weight)).toEqual([1, 1 / 2, 1 / 3, 1 / 4]);
		expect(new Set(runs.map((run) => run.jitter)).size).toBe(PLAN.passes);
		for (let i = 0; i < 10; i++) glow.update(frame(OUT));
		expect(screenRuns()).toHaveLength(PLAN.passes);
		expect(glow.busy()).toBe(false);
	});

	it('gives a pose the same passes, whatever the path to it', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, OUT);
		const first = screenRuns();
		gl.runs = [];
		settle(glow, [5000, 0, 0]);
		turn(1);
		settle(glow, [-300, 20, 0]);
		turn(0);
		gl.runs = [];
		settle(glow, OUT);
		expect(screenRuns()).toEqual(first);
	});

	it('cuts every pass at the skybox’s limit, from any place', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, OUT);
		settle(glow, [5000, 0, 0]);
		expect(gl.runs.every((run) => run.cut === GLOW_CUT_MAG)).toBe(true);
		expect(GLOW_CUT_MAG).toBe(7.5);
	});

	it('makes a new target for a new size of the view, and marches the pose again', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, OUT);
		const targets = () =>
			[...gl.live].filter((o) => 'width' in o && (o as { width: number }).width !== 64);
		expect(targets()).toHaveLength(1);
		gl.size = [1000, 501];
		gl.runs = [];
		settle(glow, OUT);
		expect(targets()).toHaveLength(1);
		expect(screenRuns()[0].size).toEqual([500, 251]);
		expect(screenRuns()).toHaveLength(PLAN.passes);
	});

	it('does not march while the stars do not draw, nor while the glow is off', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, [0, 0, 0], { drawing: false, share: 0 });
		expect(screenRuns()).toHaveLength(0);
		glow.setEnabled(false);
		settle(glow, OUT);
		expect(screenRuns()).toHaveLength(0);
		glow.setEnabled(true);
		settle(glow, OUT);
		expect(screenRuns()).toHaveLength(PLAN.passes);
	});

	it('marches the pose again after a stop, so a target never shows a pose it was not marched for', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, OUT);
		settle(glow, [0, 0, 0], { drawing: false, share: 0 });
		gl.runs = [];
		glow.update(frame([200, 0, 0]));
		expect(screenRuns()[0].origin).toEqual([200, 0, 0]);
	});

	it('takes a move far under the finest dust cell as the same pose, and marches it from where it began', async () => {
		const glow = make();
		await ready(glow);
		// A body's orbit carries the camera on: 2e-6 pc a frame is 4e-5 pc in all.
		for (let i = 0; i < 20; i++) glow.update(frame([100 + 2e-6 * i, 0, 10]));
		const runs = screenRuns();
		expect(runs.map((run) => run.weight)).toEqual([1, 1 / 2, 1 / 3, 1 / 4]);
		expect(runs.every((run) => run.origin[0] === 100)).toBe(true);
		expect(glow.stats().poseShift).toBeCloseTo(2e-4, 12);
		// A move past it is a new pose.
		glow.update(frame([100 + 3e-4, 0, 10]));
		expect(screenRuns().at(-1)).toMatchObject({ weight: 1, origin: [100 + 3e-4, 0, 10] });
	});

	it('sizes the target from CSS pixels, so a pixel ratio of 2 marches as many rays as 1', async () => {
		gl.pixelRatio = 2;
		const glow = make();
		await ready(glow);
		glow.update(frame(OUT));
		expect(screenRuns()[0].size).toEqual([800, 450]);
	});

	it('puts pass 0’s rays at the texel centres, and all passes’ about them', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, OUT);
		const offsets = screenRuns().map((run) => run.offset!);
		expect(offsets[0]).toEqual([0, 0]);
		expect(new Set(offsets.map((o) => o.join())).size).toBe(PLAN.passes);
		for (const k of [0, 1]) {
			expect(Math.abs(offsets.reduce((sum, o) => sum + o[k], 0))).toBeLessThan(1e-12);
			// The spread of a box one texel wide.
			expect(offsets.reduce((sum, o) => sum + o[k] ** 2, 0) / PLAN.passes).toBeCloseTo(1 / 12, 12);
			expect(offsets.every((o) => Math.abs(o[k]) < 0.5)).toBe(true);
		}
	});

	it('stops after pass 0 for the gates, and goes on when let', async () => {
		const glow = make();
		await ready(glow);
		glow.limitPasses(1);
		settle(glow, OUT);
		expect(screenRuns()).toHaveLength(1);
		glow.limitPasses(Infinity);
		gl.runs = [];
		settle(glow, OUT);
		expect(screenRuns().map((run) => run.weight)).toEqual([1, 1 / 2, 1 / 3, 1 / 4]);
	});
});

describe('a screen target that fails', () => {
	it('leaves the session with no glow, frees what it made, and lets the frame draw', async () => {
		const glow = make();
		await ready(glow);
		gl.failTarget = true;
		expect(() => glow.update(frame(OUT))).not.toThrow();
		expect(glow.stats().phase).toBe('none');
		expect(gl.live.size).toBe(0);
		expect(warn).toHaveBeenCalledWith('[glow] no glow on this device:', expect.any(Error));
		gl.failTarget = false;
		glow.update(frame(OUT));
		expect(screenRuns()).toHaveLength(0);
		expect(glow.busy()).toBe(false);
	});

	it('is no failure of the device on a lost context: the restore builds the glow', async () => {
		const glow = make();
		await ready(glow);
		gl.failTarget = true;
		gl.lost = true;
		glow.update(frame(OUT));
		expect(glow.stats().phase).toBe('idle');
		gl.failTarget = false;
		gl.lost = false;
		canvas.dispatchEvent(new Event('webglcontextrestored'));
		await ready(glow);
		settle(glow, OUT);
		expect(screenRuns()).toHaveLength(PLAN.passes);
		expect(warn).not.toHaveBeenCalled();
	});
});

describe('a slow device', () => {
	/** Frames of a flight, each `ms` long, from a place `start` on. */
	const fly = (glow: GlowSky, frames: number, ms: number, start: number) => {
		for (let i = 0; i < frames; i++) glow.update(frame([100 + start + i, 0, 10], { dtMs: ms }));
	};

	it('steps down to a coarser target, then fewer steps, and no further', async () => {
		const glow = make();
		await ready(glow);
		fly(glow, 31, 40, 0);
		expect(glow.stats().rung).toBe(1);
		expect(screenRuns().at(-1)?.size).toEqual([400, 225]);
		expect(gl.marches).toBe(1);
		fly(glow, 31, 40, 100);
		expect(glow.stats().rung).toBe(2);
		expect(gl.steps.at(-1)).toEqual({ screen: PLAN.steps / 2, sky: 48 });
		fly(glow, 100, 40, 200);
		expect(glow.stats()).toMatchObject({ rung: 2, judging: false });
		expect(stepDown(PLAN, 2)).toMatchObject({ divisor: 4, steps: 16, passes: PLAN.passes });
	});

	it('keeps its plan for the session once moving frames are fast, whatever comes after', async () => {
		const glow = make();
		await ready(glow);
		fly(glow, 31, 16, 0);
		expect(glow.stats()).toMatchObject({ rung: 0, judging: false });
		fly(glow, 100, 60, 100);
		expect(glow.stats().rung).toBe(0);
		expect(screenRuns().at(-1)?.size).toEqual([800, 450]);
	});

	it('judges moving frames alone: frames at rest are not its cost', async () => {
		const glow = make();
		await ready(glow);
		for (let i = 0; i < 100; i++) glow.update(frame(OUT, { dtMs: 60 }));
		expect(glow.stats()).toMatchObject({ rung: 0, judging: true });
	});

	it('keeps its steps down on a change of tier', async () => {
		const glow = make();
		await ready(glow);
		fly(glow, 31, 40, 0);
		glow.setPlan({ ...PLAN, grid: 'low', divisor: 4 });
		await ready(glow);
		glow.update(frame(OUT));
		expect(screenRuns().at(-1)?.size).toEqual([200, 113]);
	});
});

describe('exposure', () => {
	it('is the Sun’s times the gain by place, and nothing else', async () => {
		net.metadata = async () => ({ ...META, model: { centre_pc: CENTRE } });
		const glow = make();
		await ready(glow);
		for (const at of [OUT, [0, 0, 8000], [8_277, 30_000, -21]] as Vec3[]) {
			settle(glow, at);
			const shown = gl.composites[0].at(-1)!;
			expect(shown.exposure).toBeCloseTo(SUN_EXPOSURE * placeGain(at, CENTRE), 12);
		}
	});

	it('gives the dots the gain it draws with, and none where no glow can draw', async () => {
		net.metadata = async () => ({ ...META, model: { centre_pc: CENTRE } });
		const glow = make();
		expect(glow.dotsGain(OUT)).toBe(1);
		await ready(glow);
		for (const at of [OUT, [0, 0, 8000], [8_277, 30_000, -21]] as Vec3[]) {
			settle(glow, at);
			expect(glow.dotsGain(at)).toBe(glow.stats().placeGain);
		}
		expect(make(null).dotsGain(OUT)).toBeNull();
		net.metadata = async () => null;
		const none = make();
		none.update(frame([0, 0, 0]));
		await vi.advanceTimersByTimeAsync(0);
		expect(none.dotsGain(OUT)).toBeNull();
	});
});

describe('the label', () => {
	it('says the view is model while the glow of a model shows', async () => {
		net.metadata = async () => ({ ...META, model: { centre_pc: CENTRE } });
		const glow = make();
		await ready(glow);
		settle(glow, [0, 0, 0], { drawing: false, share: 0 });
		expect(glow.modelInView).toBe(false);
		settle(glow, OUT);
		expect(glow.modelInView).toBe(true);
		settle(glow, [0, 0, 0], { drawing: false, share: 0 });
		expect(glow.modelInView).toBe(false);
	});

	it('never says so on a host with no model', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, OUT);
		expect(glow.modelInView).toBe(false);
	});
});

describe('plan changes', () => {
	it('frees the old objects on a tier change, and builds the new plan', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, OUT);
		glow.setPlan({ ...PLAN, grid: 'low', divisor: 4 });
		expect(gl.live.size).toBe(0);
		await ready(glow);
		settle(glow, OUT);
		expect(gl.live.size).toBe(5);
		expect(screenRuns().at(-1)?.size).toEqual([400, 225]);
		glow.setPlan(null);
		expect(gl.live.size).toBe(0);
		glow.update(frame(OUT));
		expect(glow.busy()).toBe(false);
	});

	it('keeps the grid on a change of divisor, steps or passes, and builds the rest again', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, OUT);
		const before = new Set(gl.live);
		gl.runs = [];
		const plan = { ...PLAN, divisor: 4, steps: 16, passes: 2 };
		glow.setPlan(plan);
		expect(glow.stats().phase).toBe('uploading');
		await ready(glow);
		settle(glow, OUT);
		expect(gl.live.size).toBe(5);
		expect([...gl.live].filter((object) => before.has(object))).toHaveLength(1);
		expect(net.volumes).toBe(1);
		expect(gl.marches).toBe(2);
		expect(screenRuns()).toHaveLength(2);
	});

	it('loads again on a change of shape while the context is lost', async () => {
		const glow = make();
		await ready(glow);
		gl.lost = true;
		glow.setPlan({ ...PLAN, steps: 16 });
		expect(glow.stats().phase).toBe('idle');
	});

	it('takes a new divisor with no new march: the next frame makes the target', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, OUT);
		glow.setPlan({ ...PLAN, divisor: 4 });
		expect(glow.stats().phase).toBe('ready');
		gl.runs = [];
		settle(glow, OUT);
		expect(gl.marches).toBe(1);
		expect(screenRuns()[0].size).toEqual([400, 225]);
		expect(screenRuns()).toHaveLength(PLAN.passes);
	});

	it('keeps the grid when the dust’s nest changes under it, and builds the rest again', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, OUT);
		const before = new Set(gl.live);
		dust.marchNest = nest();
		glow.update(frame(OUT));
		await ready(glow);
		settle(glow, OUT);
		expect(gl.live.size).toBe(5);
		// Only the grid is from before, and it was not asked for again.
		expect([...gl.live].filter((object) => before.has(object))).toHaveLength(1);
		expect(net.volumes).toBe(1);
		expect(gl.marches).toBe(2);
	});

	it('waits with the grid while the dust has no nest on the GPU', async () => {
		const glow = make();
		await ready(glow);
		dust.marchNest = null;
		glow.update(frame(OUT));
		expect(gl.live.size).toBe(1);
		expect(glow.busy()).toBe(false);
		dust.marchNest = nest();
		await ready(glow);
		expect(net.volumes).toBe(1);
	});

	it('loads again after a lost context, with nothing of the old one to free', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, OUT);
		// The lost context took these; a fake keeps them.
		const lost = new Set(gl.live);
		canvas.dispatchEvent(new Event('webglcontextrestored'));
		expect(glow.stats().phase).toBe('idle');
		await ready(glow);
		glow.dispose();
		expect([...gl.live].every((object) => lost.has(object))).toBe(true);
		expect(gl.live.size).toBe(3);
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
		settle(glow, OUT);
		expect(gl.composites[0].length).toBeGreaterThan(0);
		expect(stale()).toBe(1);
		glow.setPlan({ ...PLAN, grid: 'low' });
		await ready(glow);
		expect(stale()).toBe(1);
	});
});

describe('light that is not starlight', () => {
	const withEmission = () => {
		net.emission = true;
		net.metadata = async () => ({ ...META, emission: {} });
	};
	const NEAR_SUN: Vec3 = [0.005, 0, 0];

	it('makes the map of the emission alone at the Sun once, a pass a frame, and no other', async () => {
		withEmission();
		const glow = make();
		await ready(glow);
		settle(glow, NEAR_SUN, { drawing: false, share: 0 });
		const alone = gl.runs.filter((run) => !run.screen);
		expect(alone.map((run) => run.weight)).toEqual([1, 1 / 2, 1 / 3, 1 / 4]);
		expect(alone.every((run) => run.origin.every((x) => x === 0))).toBe(true);
		expect(alone[0].size).toEqual([PLAN.sunSize, PLAN.sunSize]);
		const before = gl.runs.length;
		settle(glow, OUT);
		expect(gl.runs.slice(before).some((run) => !run.screen)).toBe(false);
		expect(glow.stats().emission?.sunMap).toBe(true);
	});

	it('draws the emission alone over the skybox inside the solar system, and the far regions on both sides', async () => {
		withEmission();
		const glow = make();
		await ready(glow);
		settle(glow, NEAR_SUN, { drawing: false, share: 0, skybox: 0.8 });
		const [outside, , inside] = gl.composites;
		expect(outside.length).toBe(0);
		expect(inside.at(-1)?.share).toBeCloseTo(0.8, 6);
		expect(gl.regions.at(-1)).toBeCloseTo(0.8, 6);
		settle(glow, OUT, { skybox: 0 });
		expect(outside.at(-1)?.share).toBe(1);
		expect(gl.regions.at(-1)).toBe(1);
	});

	it('shares the sky past the join between the march and the sky from the Sun', async () => {
		withEmission();
		const glow = make(PLAN, SKYBOX);
		await ready(glow);
		const [outside, cube, inside] = gl.composites;
		for (const [at, join] of [
			[[1, 0, 0], joinShare(1)],
			[[3, 0, 0], joinShare(3)],
			[OUT, 1]
		] as [Vec3, number][]) {
			settle(glow, at, { skybox: 0, skyboxLayer: true });
			expect(join).toBeGreaterThan(0);
			expect(outside.at(-1)?.share).toBeCloseTo(join, 9);
			if (join < 1) {
				expect(cube.at(-1)?.share).toBeCloseTo(1 - join, 9);
				expect(inside.at(-1)?.share).toBeCloseTo(1 - join, 9);
				// The sky from the Sun takes the place's gain as the march does.
				expect(cube.at(-1)?.exposure).toBe(glow.stats().placeGain);
			}
			expect(gl.regions.at(-1)).toBe(1);
		}
		const shown = cube.length;
		settle(glow, [1, 0, 0], { skybox: 0, skyboxLayer: false });
		expect(cube.length).toBe(shown);
	});

	it('follows the stars’ share of the sky alone as they take it, so the skybox and it sum to one', async () => {
		withEmission();
		const glow = make(PLAN, SKYBOX);
		await ready(glow);
		const cube = gl.composites[1];
		const at: Vec3 = [0.0105, 0, 0];
		settle(glow, at, { share: 0, skybox: 1, skyboxLayer: true });
		for (const share of [0.25, 0.5, 1]) {
			glow.update(frame(at, { share, skybox: 1 - share, skyboxLayer: true }));
			expect(cube.at(-1)?.share).toBeCloseTo(share * (1 - joinShare(0.0105)), 9);
		}
	});

	it('is not busy inside the solar system after a flight that left the passes unfinished', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, OUT);
		turn(0.3);
		glow.update(frame(OUT));
		expect(glow.stats().pass).toBeLessThan(PLAN.passes);
		glow.update(frame([0.001, 0, 0], { share: 0, skybox: 1 }));
		expect(glow.busy()).toBe(false);
	});

	it('reads the sky without its bright stars past the join, loaded at the first crossing', async () => {
		withEmission();
		const skybox = SKYBOX();
		const starless = new CubeTexture();
		starless.userData.faceTexels = 256;
		let resolve: (cube: CubeTexture | null) => void = () => {};
		const load = vi.fn(() => new Promise<CubeTexture | null>((r) => (resolve = r)));
		const glow = make(PLAN, () => skybox, new StarlessSky(load, () => {}));
		await ready(glow);
		settle(glow, NEAR_SUN, { drawing: false, share: 0, skybox: 1, skyboxLayer: true });
		expect(load).not.toHaveBeenCalled();
		const cube = gl.composites[1];
		for (let i = 0; i < 100 && load.mock.calls.length === 0; i++)
			glow.update(frame([1, 0, 0], { skybox: 0, skyboxLayer: true }));
		expect(load).toHaveBeenCalledTimes(1);
		// Until it loads, the skybox at the mip of the glow's size.
		expect(cube.at(-1)).toMatchObject({ map: skybox.texture, lod: 4 });
		expect(glow.busy()).toBe(true);
		resolve(starless);
		await vi.advanceTimersByTimeAsync(0);
		settle(glow, [1, 0, 0], { skybox: 0, skyboxLayer: true });
		expect(cube.at(-1)).toMatchObject({ map: starless, lod: 0 });
		expect(load).toHaveBeenCalledTimes(1);
	});

	it('keeps the skybox past the join where the export has no starless sky', async () => {
		withEmission();
		const skybox = SKYBOX();
		const load = vi.fn(async () => null);
		const glow = make(PLAN, () => skybox, new StarlessSky(load, () => {}));
		await ready(glow);
		for (let i = 0; i < 100 && load.mock.calls.length === 0; i++)
			glow.update(frame([1, 0, 0], { skybox: 0, skyboxLayer: true }));
		await vi.advanceTimersByTimeAsync(0);
		settle(glow, [1, 0, 0], { skybox: 0, skyboxLayer: true });
		expect(gl.composites[1].at(-1)).toMatchObject({ map: skybox.texture, lod: 4 });
		expect(load).toHaveBeenCalledTimes(1);
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

	it('turns off for the gates: the march is built again as on a host with none', async () => {
		withEmission();
		const glow = make();
		await ready(glow);
		settle(glow, OUT);
		glow.setEmission({ halpha: false, scatter: false, regions: false });
		gl.runs = [];
		await ready(glow);
		settle(glow, OUT, { skybox: 0 });
		expect(gl.parts.at(-1)).toEqual({ halpha: false, scatter: false, regions: false });
		expect(gl.runs.some((run) => !run.screen)).toBe(false);
		// The grid, the emission's textures, the march, the composites of the
		// march and the skybox and the target; no map of the emission alone, no
		// composite for it, no regions.
		expect(gl.live.size).toBe(6);
		glow.setEmission({ halpha: true, scatter: true, regions: true });
		await ready(glow);
		settle(glow, OUT, { skybox: 0 });
		expect(gl.live.size).toBe(9);
	});

	it('loads none of it, and draws the rest, on a host with none', async () => {
		const glow = make();
		await ready(glow);
		settle(glow, NEAR_SUN, { drawing: false, share: 0, skybox: 1 });
		expect(gl.composites.length).toBe(2);
		expect(gl.regions.length).toBe(0);
		expect(glow.stats().emission).toBeNull();
	});
});
