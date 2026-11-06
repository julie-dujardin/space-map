/**
 * The eye's questions to the GPU. The passes are fakes, and the GL context
 * answers each occlusion query when a test says so.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WebGLRenderer } from 'three';
import type { SkyMap } from '$lib/scene/dust/march';
import { GlowEye } from './eye';

interface FakeQuery {
	available: boolean;
	drew: boolean;
	/** Questions sent on this query. */
	sent: number;
}

const gpu = vi.hoisted(() => ({
	queries: [] as FakeQuery[],
	/** The share of each question on the model's share, in order. */
	shares: [] as number[],
	lost: false
}));

vi.mock('$lib/scene/dust/march', () => ({
	FullscreenPass: class {
		uniform(name: string) {
			return name;
		}
		samplers() {}
		run(_target: unknown, bind: (gl: unknown) => void) {
			bind(gl);
		}
		dispose() {}
	}
}));

const gl = new Proxy(
	{
		ANY_SAMPLES_PASSED: 1,
		QUERY_RESULT_AVAILABLE: 2,
		QUERY_RESULT: 3,
		FRAMEBUFFER_COMPLETE: 4,
		createQuery: () => {
			const query: FakeQuery = { available: false, drew: false, sent: 0 };
			gpu.queries.push(query);
			return query;
		},
		beginQuery: (_target: number, query: FakeQuery) => {
			query.available = false;
			query.sent++;
		},
		getQueryParameter: (query: FakeQuery, name: number) =>
			name === 2 ? query.available : Number(query.drew),
		checkFramebufferStatus: () => 4,
		uniform1f: (location: string, value: number) => {
			if (location === 'uShare') gpu.shares.push(value);
		},
		isContextLost: () => gpu.lost,
		createTexture: () => ({}),
		createFramebuffer: () => ({})
	} as Record<string | symbol, unknown>,
	{ get: (target, key) => (key in target ? target[key] : () => {}) }
);

const renderer = {
	getContext: () => gl,
	state: { bindTexture() {}, bindFramebuffer() {} },
	setRenderTarget() {},
	getRenderTarget: () => null
} as unknown as WebGLRenderer;

const map = (): SkyMap => ({ texture: {} }) as unknown as SkyMap;

/** The GPU answers a query's last question. */
function answer(query: FakeQuery, drew: boolean): void {
	query.available = true;
	query.drew = drew;
}

beforeEach(() => {
	gpu.queries = [];
	gpu.shares = [];
	gpu.lost = false;
});

describe('the question on the model’s share', () => {
	it('goes again for the front map when two maps take over before the first answer', () => {
		const eye = new GlowEye(renderer, 64);
		const [, share] = gpu.queries;
		eye.measure(map(), false);
		eye.askShare(0.25);
		eye.measure(map(), false);
		eye.askShare(0.2);
		expect(share.sent).toBe(1);
		expect(eye.shareAnswer()).toBeNull();
		expect(eye.sharePending).toBe(true);
		// The answer of the first map is moot: the question goes again.
		answer(share, false);
		expect(eye.shareAnswer()).toBeNull();
		expect(share.sent).toBe(2);
		expect(gpu.shares).toEqual([0.25, 0.2]);
		expect(eye.sharePending).toBe(true);
		answer(share, true);
		expect(eye.shareAnswer()).toBe(true);
		expect(eye.sharePending).toBe(false);
		expect(eye.shareAnswer()).toBeNull();
	});

	it('keeps its answer when only the map at the Sun is measured meanwhile', () => {
		const eye = new GlowEye(renderer, 64);
		const [, share] = gpu.queries;
		eye.measure(map(), false);
		eye.askShare(0.25);
		eye.measure(map(), true);
		answer(share, true);
		expect(eye.shareAnswer()).toBe(true);
		expect(share.sent).toBe(1);
	});

	it('is dropped on a lost context, so nothing waits for it', () => {
		const eye = new GlowEye(renderer, 64);
		eye.measure(map(), false);
		eye.askShare(0.25);
		gpu.lost = true;
		expect(eye.shareAnswer()).toBeNull();
		expect(eye.sharePending).toBe(false);
	});
});

describe('the question on the eye’s target', () => {
	it('does not go again by itself when a new mean makes it moot', () => {
		const eye = new GlowEye(renderer, 64);
		const [close] = gpu.queries;
		eye.ask();
		eye.measure(map(), false);
		answer(close, false);
		expect(eye.answer()).toBeNull();
		expect(close.sent).toBe(1);
		eye.ask();
		answer(close, false);
		expect(eye.answer()).toBe(true);
	});
});
