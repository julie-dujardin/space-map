/**
 * The scene loads global.json once at boot and goes on without it: on a bad
 * line every moon then spins without its nutation terms, Mimas's 45° off in
 * 2026. While a map listens, the file is asked for again until it loads, or
 * the data host says it has none. Each test loads the module afresh, so
 * global.json starts out not loaded.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

type SystemsGlobal = typeof import('./systems-global');

const SUMS = { ra: [1], dec: [2], pm: [3] };
const GLOBAL = { nut_prec_angles: { 6: [316.45, 506.2] } };

/** A fetch that answers each call with the next of `answers`, an Error being
 *  a failed request. */
function answering(answers: (() => Response | Error)[]) {
	const fetch = vi.fn(async () => {
		const answer = answers.shift()?.() ?? new Error('no answer');
		if (answer instanceof Error) throw answer;
		return answer;
	});
	vi.stubGlobal('fetch', fetch);
	return fetch;
}

const ok = () => Response.json(GLOBAL);
const status = (code: number) => () => new Response(null, { status: code });
const down = () => new TypeError('Failed to fetch');

let systems: SystemsGlobal;

beforeEach(async () => {
	vi.useFakeTimers();
	// No spread on the waits: 2 s, 4 s, 8 s…
	vi.spyOn(Math, 'random').mockReturnValue(0.5);
	vi.resetModules();
	systems = await import('./systems-global');
});

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

describe('nutPrecAwaited', () => {
	it('holds for the sums of a NAIF body until global.json loads', async () => {
		expect(systems.nutPrecAwaited('naif-601', SUMS)).toBe(true);
		expect(systems.nutPrecAwaited('naif-601', undefined)).toBe(false);
		expect(systems.nutPrecAwaited('spkid-20000433', SUMS)).toBe(false);
		answering([ok]);
		await systems.loadSystemsGlobal();
		expect(systems.nutPrecAwaited('naif-601', SUMS)).toBe(false);
	});

	it('holds no longer once the data host says it has no global.json', async () => {
		answering([status(404)]);
		await expect(systems.loadSystemsGlobal()).rejects.toThrow('404');
		expect(systems.nutPrecAwaited('naif-601', SUMS)).toBe(false);
	});
});

describe('onSystemsGlobalSettled', () => {
	it('tells a listener once, whichever call loads the file', async () => {
		answering([down, ok]);
		await expect(systems.loadSystemsGlobal()).rejects.toThrow();
		const listener = vi.fn();
		systems.onSystemsGlobalSettled(listener);
		expect(listener).not.toHaveBeenCalled();
		await systems.loadSystemsGlobal();
		await systems.loadSystemsGlobal();
		expect(listener).toHaveBeenCalledTimes(1);
	});

	it('tells a listener at once when the file has loaded', async () => {
		answering([ok]);
		await systems.loadSystemsGlobal();
		const listener = vi.fn();
		systems.onSystemsGlobalSettled(listener);
		expect(listener).toHaveBeenCalledTimes(1);
	});

	it('tells the other listeners, and loads, when one listener throws', async () => {
		answering([down, ok]);
		await expect(systems.loadSystemsGlobal()).rejects.toThrow();
		vi.spyOn(console, 'error').mockImplementation(() => {});
		const after = vi.fn();
		systems.onSystemsGlobalSettled(() => {
			throw new Error('a bad listener');
		});
		systems.onSystemsGlobalSettled(after);
		await expect(systems.loadSystemsGlobal()).resolves.toBeUndefined();
		expect(after).toHaveBeenCalledTimes(1);
	});

	it('asks again, waiting twice as long after each failure, until the file loads', async () => {
		const fetch = answering([down, status(503), down, ok]);
		const listener = vi.fn();
		systems.onSystemsGlobalSettled(listener);
		await vi.advanceTimersByTimeAsync(0);
		expect(fetch).toHaveBeenCalledTimes(1);
		await vi.advanceTimersByTimeAsync(1_999);
		expect(fetch).toHaveBeenCalledTimes(1);
		await vi.advanceTimersByTimeAsync(1);
		expect(fetch).toHaveBeenCalledTimes(2);
		await vi.advanceTimersByTimeAsync(3_999);
		expect(fetch).toHaveBeenCalledTimes(2);
		await vi.advanceTimersByTimeAsync(1);
		expect(fetch).toHaveBeenCalledTimes(3);
		await vi.advanceTimersByTimeAsync(8_000);
		expect(fetch).toHaveBeenCalledTimes(4);
		expect(listener).toHaveBeenCalledTimes(1);
		expect(systems.nutPrecFor('naif-601', SUMS)).toEqual({
			...SUMS,
			angles: [316.45, 506.2],
			phaseDegree: 1
		});
	});

	it('waits out a failure from before it listened', async () => {
		const fetch = answering([status(503), ok]);
		await expect(systems.loadSystemsGlobal()).rejects.toThrow('503');
		systems.onSystemsGlobalSettled(() => {});
		await vi.advanceTimersByTimeAsync(1_999);
		expect(fetch).toHaveBeenCalledTimes(1);
		await vi.advanceTimersByTimeAsync(1);
		expect(fetch).toHaveBeenCalledTimes(2);
	});

	it('stops asking once the data host says it has no global.json, and says so', async () => {
		const fetch = answering([status(404), ok]);
		const listener = vi.fn();
		systems.onSystemsGlobalSettled(listener);
		await vi.advanceTimersByTimeAsync(10 * 60_000);
		expect(fetch).toHaveBeenCalledTimes(1);
		expect(listener).toHaveBeenCalledTimes(1);
	});

	it('stops asking once no one listens', async () => {
		const fetch = answering([down, down, down]);
		const stop = systems.onSystemsGlobalSettled(() => {});
		await vi.advanceTimersByTimeAsync(0);
		stop();
		await vi.advanceTimersByTimeAsync(10 * 60_000);
		expect(fetch).toHaveBeenCalledTimes(1);
	});

	it('waits for the line to come back', async () => {
		const window = new EventTarget();
		vi.stubGlobal('window', window);
		vi.stubGlobal('navigator', { onLine: false });
		const fetch = answering([ok]);
		systems.onSystemsGlobalSettled(() => {});
		await vi.advanceTimersByTimeAsync(10 * 60_000);
		expect(fetch).not.toHaveBeenCalled();
		vi.stubGlobal('navigator', { onLine: true });
		window.dispatchEvent(new Event('online'));
		await vi.advanceTimersByTimeAsync(0);
		expect(fetch).toHaveBeenCalledTimes(1);
		expect(systems.nutPrecAwaited('naif-601', SUMS)).toBe(false);
	});
});
