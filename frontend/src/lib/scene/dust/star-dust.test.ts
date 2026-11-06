/**
 * The plan transitions of `StarDust`: a tier change in any phase, a device that
 * cannot make a map, a context lost before or during the build, a load that
 * fails, and the origin on the way to and from the Sun. The GL classes are fakes that count what they hold,
 * so a leak shows as a number.
 */

import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import type { WebGLRenderer } from 'three';
import { starUniforms } from '$lib/scene/starfield/material';
import type { NestLevel, NestMetadata, NestTier } from './nest';
import { NestFormatError } from './nest';
import type { Vec3 } from './octahedral';
import { StarDust, type DustPlan } from './star-dust';

const gl = vi.hoisted(() => ({
	/** Fake GL objects made and not yet disposed. */
	live: new Set<object>(),
	made: { gpu: 0, march: 0, map: 0 },
	runs: [] as { map: object; origin: number[] }[],
	canMarch: true,
	failMarch: false,
	/** The map that throws on construction, counted from 1. */
	failMapAt: 0,
	/** Frames a nest takes to upload. */
	uploadFrames: 2,
	lost: false
}));

const net = vi.hoisted(() => ({
	calls: { metadata: 0, low: 0, high: 0 },
	metadata: null as (() => Promise<unknown>) | null,
	levels: null as ((tier: string) => Promise<unknown>) | null
}));

vi.mock('./march', () => {
	class NestTextures {
		steps = 0;
		constructor(
			_renderer: unknown,
			readonly levels: readonly unknown[]
		) {
			gl.made.gpu++;
			gl.live.add(this);
		}
		get uploaded(): boolean {
			return this.steps >= gl.uploadFrames;
		}
		step(): void {
			this.steps++;
		}
		dispose(): void {
			gl.live.delete(this);
		}
	}
	class DustMarch {
		constructor() {
			if (gl.failMarch) throw new Error('dust march: link failed');
			gl.made.march++;
			gl.live.add(this);
		}
		run(map: object, origin: number[]): void {
			gl.runs.push({ map, origin: [...origin] });
		}
		dispose(): void {
			gl.live.delete(this);
		}
	}
	class SkyMap {
		external = {};
		constructor() {
			if (++gl.made.map === gl.failMapAt) throw new Error('dust: map framebuffer 36054');
			gl.live.add(this);
		}
		dispose(): void {
			gl.live.delete(this);
		}
	}
	return { NestTextures, DustMarch, SkyMap, canMarch: () => gl.canMarch };
});

vi.mock('./nest', async (importActual) => {
	const actual = await importActual<typeof import('./nest')>();
	return {
		...actual,
		fetchNestMetadata: () => {
			net.calls.metadata++;
			return net.metadata!();
		},
		fetchNestLevels: (_meta: unknown, tier: NestTier) => {
			net.calls[tier]++;
			return net.levels!(tier);
		}
	};
});

const FLOOR = 1e-6;
const SPAN = Math.log1p(0.1 / FLOOR);

/** A nest of one dense density, so the reach of any origin is 0.05 pc. */
function denseLevel(): NestLevel {
	const code = Math.round((Math.log1p(0.01 / FLOOR) / SPAN) * 255);
	return {
		half: [100, 100, 100],
		floor: FLOOR,
		span: SPAN,
		size: [8, 8, 8],
		codes: new Uint8Array(512).fill(code)
	};
}

const META = {
	format: 1,
	token: 'abc',
	distribution: 'open',
	frame: {
		rotation_to_icrs: [
			[1, 0, 0],
			[0, 1, 0],
			[0, 0, 1]
		]
	},
	levels: [],
	credits: []
} as unknown as NestMetadata;

const MAP: DustPlan = { mode: 'map', nest: 'high', passes: 2 };
const MAP_LOW: DustPlan = { mode: 'map', nest: 'low', passes: 2 };
const NODE: DustPlan = { mode: 'node', nest: 'low', passes: 1 };
const HOME: Vec3 = [0, 0, 0];
const AWAY: Vec3 = [3, 0, 0];

let clock = 0;
let changes = 0;
let warn: MockInstance;
let canvas: EventTarget;

function make(plan: DustPlan): StarDust {
	canvas = new EventTarget();
	const renderer = { domElement: canvas, getContext: () => ({ isContextLost: () => gl.lost }) };
	return new StarDust(renderer as unknown as WebGLRenderer, plan, () => changes++);
}

/** Drawn frames of 16 ms with the camera at `at`. */
function frames(dust: StarDust, count: number, at: Vec3 = HOME, drawing = true, dtMs = 16): void {
	for (let i = 0; i < count; i++) {
		clock += dtMs;
		dust.update(at, true, drawing, clock, dtMs);
	}
}

const flush = () => vi.advanceTimersByTimeAsync(0);

/** Frames, each followed by what the loads have to say, until the phase is `phase`. */
async function until(dust: StarDust, phase: string, at: Vec3 = HOME): Promise<void> {
	for (let i = 0; i < 40 && dust.stats().phase !== phase; i++) {
		frames(dust, 1, at);
		await flush();
	}
	expect(dust.stats().phase).toBe(phase);
}

/** Frames until the dust has nothing left to do. */
function settle(dust: StarDust, at: Vec3): void {
	for (let i = 0; i < 60 && dust.busy(); i++) frames(dust, 1, at);
	expect(dust.busy()).toBe(false);
}

const alive = (): number => gl.live.size;

beforeEach(() => {
	vi.useFakeTimers();
	clock = 0;
	changes = 0;
	gl.live.clear();
	gl.made = { gpu: 0, march: 0, map: 0 };
	gl.runs = [];
	gl.canMarch = true;
	gl.failMarch = false;
	gl.failMapAt = 0;
	gl.uploadFrames = 2;
	gl.lost = false;
	net.calls = { metadata: 0, low: 0, high: 0 };
	net.metadata = async () => META;
	net.levels = async () => [denseLevel()];
	warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => {
	vi.useRealTimers();
	vi.restoreAllMocks();
});

describe('loading a plan', () => {
	it('builds the nest, the march and three maps for a map plan', async () => {
		const dust = make(MAP);
		await until(dust, 'ready');
		expect(dust.stats().mode).toBe('map');
		expect(gl.made).toEqual({ gpu: 1, march: 1, map: 3 });
		expect(alive()).toBe(5);
		expect(net.calls).toEqual({ metadata: 1, low: 1, high: 1 });
	});

	it('builds no GL object for a node plan', async () => {
		const dust = make(NODE);
		await until(dust, 'ready');
		expect(alive()).toBe(0);
		expect(dust.nodeMode).toBe(true);
	});

	it('goes without a map where the context cannot draw one', async () => {
		gl.canMarch = false;
		const dust = make(MAP);
		expect(dust.stats().mode).toBe('node');
		await until(dust, 'ready');
		expect(alive()).toBe(0);
	});
});

describe('a tier change', () => {
	it('frees the maps and the nest on the way to a node plan', async () => {
		const dust = make(MAP);
		await until(dust, 'ready');
		dust.setPlan(NODE);
		expect(alive()).toBe(0);
		await until(dust, 'ready');
		expect(dust.nodeMode).toBe(true);
		expect(alive()).toBe(0);
		// The CPU nest stays: it is the same for every tier.
		expect(net.calls.low).toBe(1);
	});

	it('lets go of the sky maps in the uniforms, which a plan change disposed', async () => {
		const dust = make(MAP);
		await until(dust, 'ready', AWAY);
		settle(dust, AWAY);
		const uniforms = starUniforms();
		dust.apply(uniforms);
		expect(uniforms.uDustCam.value).not.toBeNull();
		expect(uniforms.uDustSun.value).not.toBeNull();
		dust.setPlan(NODE);
		dust.apply(uniforms);
		expect(uniforms.uDustCam.value).toBeNull();
		expect(uniforms.uDustSun.value).toBeNull();
		await until(dust, 'ready', AWAY);
		settle(dust, AWAY);
		dust.apply(uniforms);
		expect(uniforms.uDustCam.value).toBeNull();
	});

	it('swaps the high nest for the low one without a second fetch of the low', async () => {
		const dust = make(MAP);
		await until(dust, 'ready');
		dust.setPlan(MAP_LOW);
		expect(alive()).toBe(0);
		await until(dust, 'ready');
		expect(dust.stats().nest).toBe('low');
		expect(gl.made).toEqual({ gpu: 2, march: 2, map: 6 });
		expect(alive()).toBe(5);
		expect(net.calls).toEqual({ metadata: 1, low: 1, high: 1 });
	});

	it('swaps the low nest for the high one', async () => {
		const dust = make(MAP_LOW);
		await until(dust, 'ready');
		dust.setPlan(MAP);
		expect(alive()).toBe(0);
		await until(dust, 'ready');
		expect(dust.stats().nest).toBe('high');
		expect(alive()).toBe(5);
		expect(net.calls).toEqual({ metadata: 1, low: 1, high: 1 });
	});

	it('builds a map on the way from a node plan', async () => {
		const dust = make(NODE);
		await until(dust, 'ready');
		dust.setPlan(MAP);
		await until(dust, 'ready');
		expect(dust.nodeMode).toBe(false);
		expect(alive()).toBe(5);
		expect(net.calls.low).toBe(1);
	});

	it('does not restart for a change that only the passes see', async () => {
		const dust = make(MAP);
		await until(dust, 'ready');
		dust.setPlan({ ...MAP, passes: 4 });
		expect(dust.stats().phase).toBe('ready');
		expect(gl.made.gpu).toBe(1);
	});

	it('does not restart a node plan for another nest', async () => {
		const dust = make(NODE);
		await until(dust, 'ready');
		dust.setPlan({ ...NODE, nest: 'high' });
		expect(dust.stats().phase).toBe('ready');
	});

	it('ends in the new plan when it comes while the nest is loading', async () => {
		let release!: () => void;
		const held = new Promise<void>((resolve) => (release = resolve));
		net.levels = async () => {
			await held;
			return [denseLevel()];
		};
		const dust = make(MAP);
		frames(dust, 1);
		await flush();
		expect(dust.stats().phase).toBe('loading');
		dust.setPlan(NODE);
		release();
		await flush();
		// The load that was on its way is dropped, and it builds nothing.
		expect(alive()).toBe(0);
		await until(dust, 'ready');
		expect(dust.nodeMode).toBe(true);
		expect(alive()).toBe(0);
	});

	it('frees a nest that is part way up when the plan changes', async () => {
		gl.uploadFrames = 50;
		const dust = make(MAP);
		await until(dust, 'uploading');
		expect(alive()).toBe(1);
		gl.uploadFrames = 2;
		dust.setPlan(NODE);
		expect(alive()).toBe(0);
		await until(dust, 'ready');
		expect(dust.nodeMode).toBe(true);
		expect(alive()).toBe(0);
	});

	it('starts nothing before the camera is out', async () => {
		const dust = make(MAP);
		dust.setPlan(NODE);
		await flush();
		expect(net.calls.metadata).toBe(0);
		expect(dust.stats().phase).toBe('idle');
	});

	it('leaves a host with no nest alone', async () => {
		net.metadata = async () => null;
		const dust = make(MAP);
		await until(dust, 'none');
		dust.setPlan(NODE);
		await flush();
		frames(dust, 3);
		expect(dust.stats().phase).toBe('none');
		expect(net.calls.metadata).toBe(1);
	});
});

describe('the origin', () => {
	it('does not carry a node plan origin into a map plan', async () => {
		const dust = make(NODE);
		await until(dust, 'ready');
		frames(dust, 1, AWAY);
		expect(dust.stats().origin).toEqual(AWAY);
		dust.setPlan(MAP);
		expect(dust.stats().origin).toEqual(HOME);
		await until(dust, 'ready', AWAY);
		// The front map has not been made for any origin yet, so no star reads it.
		const uniforms = starUniforms();
		uniforms.uDustShare.value = 1;
		dust.apply(uniforms);
		expect(uniforms.uDustShare.value).toBe(0);
	});

	it('reads the front map once it is made for the origin', async () => {
		const dust = make(MAP);
		await until(dust, 'ready', AWAY);
		settle(dust, AWAY);
		expect(dust.stats().origin).toEqual(AWAY);
		const uniforms = starUniforms();
		dust.apply(uniforms);
		expect(uniforms.uDustShare.value).toBeGreaterThan(0);
		expect(uniforms.uDustCam.value).not.toBeNull();
	});

	for (const [name, plan] of [
		['a map', MAP],
		['rays', NODE]
	] as const) {
		it(`goes back to the Sun with ${name} while no star draws`, async () => {
			const dust = make(plan);
			await until(dust, 'ready', AWAY);
			frames(dust, 1, AWAY);
			settle(dust, AWAY);
			expect(dust.stats().origin).toEqual(AWAY);
			const epoch = dust.epoch;
			frames(dust, 1, HOME, false);
			expect(dust.stats().origin).toEqual(HOME);
			expect(dust.epoch).toBeGreaterThan(epoch);
			const uniforms = starUniforms();
			dust.apply(uniforms);
			expect(uniforms.uDustShare.value).toBe(0);
		});
	}

	it('leaves no job on a camera that left while no star draws', async () => {
		const dust = make(MAP);
		await until(dust, 'ready');
		settle(dust, HOME);
		frames(dust, 1, AWAY);
		expect(dust.busy()).toBe(true);
		frames(dust, 1, AWAY, false);
		expect(dust.busy()).toBe(false);
	});
});

describe('a device that passes the check and cannot make a map', () => {
	it('falls back to rays when the march does not link, and warns once', async () => {
		gl.failMarch = true;
		const dust = make(MAP);
		await until(dust, 'ready');
		expect(dust.stats().mode).toBe('node');
		expect(dust.nodeMode).toBe(true);
		// The nest that was part way up goes with it.
		expect(alive()).toBe(0);
		frames(dust, 20, AWAY);
		expect(warn).toHaveBeenCalledTimes(1);
		expect(gl.made.march).toBe(0);
	});

	it('frees the maps made before one that did not complete', async () => {
		gl.failMapAt = 3;
		const dust = make(MAP);
		await until(dust, 'ready');
		expect(dust.stats().mode).toBe('node');
		expect(alive()).toBe(0);
		expect(warn).toHaveBeenCalledTimes(1);
	});

	it('keeps to rays for the session, also when the tier changes', async () => {
		gl.failMarch = true;
		const dust = make(MAP);
		await until(dust, 'ready');
		gl.failMarch = false;
		dust.setPlan(MAP);
		expect(dust.stats().mode).toBe('node');
		dust.setPlan(MAP_LOW);
		expect(dust.stats().phase).toBe('ready');
		expect(gl.made.march).toBe(0);
	});
});

describe('a lost context', () => {
	it('starts again on the restored one, and takes nothing from the old one', async () => {
		const dust = make(MAP);
		await until(dust, 'ready', AWAY);
		settle(dust, AWAY);
		canvas.dispatchEvent(new Event('webglcontextrestored'));
		expect(dust.stats().phase).toBe('idle');
		expect(dust.stats().origin).toEqual(HOME);
		await until(dust, 'ready');
		expect(gl.made.gpu).toBe(2);
		expect(net.calls.low).toBe(1);
	});

	it('is no failure of the device during the build: the restore builds the maps', async () => {
		const dust = make(MAP);
		await until(dust, 'uploading');
		// On a lost context the march does not link.
		gl.lost = true;
		gl.failMarch = true;
		frames(dust, 5);
		await flush();
		expect(dust.stats().phase).toBe('idle');
		expect(dust.stats().mode).toBe('map');
		expect(dust.busy()).toBe(false);
		// Nothing loads on the lost context.
		expect(net.calls).toEqual({ metadata: 1, low: 1, high: 1 });
		gl.lost = false;
		gl.failMarch = false;
		canvas.dispatchEvent(new Event('webglcontextrestored'));
		await until(dust, 'ready');
		expect(dust.stats().mode).toBe('map');
		expect(gl.made.march).toBe(1);
		expect(warn).not.toHaveBeenCalled();
	});
});

describe('a load that fails', () => {
	it('ends for a format it cannot read', async () => {
		net.levels = async () => {
			throw new NestFormatError('dust levels/0.bin.gz: kind 3, not a volume');
		};
		const dust = make(NODE);
		await until(dust, 'none');
		await vi.advanceTimersByTimeAsync(120_000);
		frames(dust, 5);
		expect(net.calls.low).toBe(1);
		expect(warn).toHaveBeenCalledTimes(1);
	});

	it('tries again for a network error', async () => {
		let failures = 1;
		net.levels = async () => {
			if (failures-- > 0) throw new Error('503');
			return [denseLevel()];
		};
		const dust = make(NODE);
		frames(dust, 1);
		await flush();
		expect(dust.stats().phase).toBe('idle');
		await vi.advanceTimersByTimeAsync(5_000);
		await until(dust, 'ready');
		expect(net.calls.low).toBe(2);
	});

	it('fetches the low nest once for loads that overlap', async () => {
		let release!: () => void;
		const held = new Promise<void>((resolve) => (release = resolve));
		net.levels = async () => {
			await held;
			return [denseLevel()];
		};
		const dust = make(MAP);
		frames(dust, 1);
		await flush();
		// A restore while the first load is out starts a second one.
		canvas.dispatchEvent(new Event('webglcontextrestored'));
		frames(dust, 1);
		await flush();
		release();
		await until(dust, 'ready');
		expect(net.calls.low).toBe(1);
	});

	it('keeps the low nest when the high one fails', async () => {
		let failures = 1;
		net.levels = async (tier) => {
			if (tier === 'high' && failures-- > 0) throw new Error('503');
			return [denseLevel()];
		};
		const dust = make(MAP);
		frames(dust, 1);
		await flush();
		await vi.advanceTimersByTimeAsync(5_000);
		await until(dust, 'ready');
		expect(net.calls).toEqual({ metadata: 1, low: 1, high: 2 });
	});
});

describe('the pacer', () => {
	it('draws the frame after the last pass, so that its length is not a rest', async () => {
		const dust = make(MAP);
		await until(dust, 'ready');
		settle(dust, HOME);
		frames(dust, 1, AWAY);
		// Two passes make a map. The second one swaps it in and nothing is left,
		// but the frame after it is the one that tells what it cost.
		frames(dust, 1, AWAY);
		expect(dust.stats().refreshes).toBe(1);
		expect(dust.busy()).toBe(true);
		frames(dust, 1, AWAY);
		expect(dust.busy()).toBe(false);
	});

	it('does not read a gap after a rest as the cost of a pass', async () => {
		const dust = make(MAP);
		await until(dust, 'ready');
		settle(dust, HOME);
		frames(dust, 2, AWAY);
		settle(dust, AWAY);
		frames(dust, 1, AWAY, true, 250);
		expect(dust.stats().intervalMs).toBe(0);
	});

	it('waits longer between refreshes where frames are slow', async () => {
		const dust = make(NODE);
		await until(dust, 'ready');
		const camera = (i: number): Vec3 => [1 + i, 0, 0];
		for (let i = 0; i < 20; i++) frames(dust, 1, camera(i), true, 40);
		const slow = dust.stats().refreshes;
		expect(dust.stats().intervalMs).toBeGreaterThan(0);
		expect(slow).toBeLessThan(10);

		const quick = make(NODE);
		await until(quick, 'ready');
		for (let i = 0; i < 20; i++) frames(quick, 1, camera(i), true, 16);
		expect(quick.stats().refreshes).toBe(20);
	});

	it('leaves the origin of rays alone while the camera stays in its reach', async () => {
		const dust = make(NODE);
		await until(dust, 'ready');
		frames(dust, 1, AWAY);
		settle(dust, AWAY);
		const epoch = dust.epoch;
		frames(dust, 5, AWAY);
		expect(dust.epoch).toBe(epoch);
	});
});
