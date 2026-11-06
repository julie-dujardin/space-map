/**
 * What a `GpuLoad` leaves behind once its owner disposes it: no timer of a
 * retry that calls the owner later.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { WebGLRenderer } from 'three';
import { GpuLoad } from './gpu-load';

const renderer = {
	domElement: new EventTarget(),
	getContext: () => ({ isContextLost: () => false })
} as unknown as WebGLRenderer;

/** A load whose metadata or data fails with an error a retry can pass. */
function failing(at: 'metadata' | 'data') {
	const onChange = vi.fn();
	const load = new GpuLoad<object, object>(
		renderer,
		'test',
		'the data',
		{
			metadata: async () => {
				if (at === 'metadata') throw new Error('metadata.json returned 503');
				return {};
			},
			received: () => 'ready',
			release: () => {},
			reset: () => {}
		},
		onChange
	);
	load.start(async () => {
		throw new Error('data returned 503');
	});
	return { load, onChange };
}

beforeEach(() => {
	vi.useFakeTimers();
	vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => {
	vi.useRealTimers();
	vi.restoreAllMocks();
});

describe('a load that waits to retry', () => {
	it.each(['metadata', 'data'] as const)(
		'calls its owner when the wait of its %s ends',
		async (at) => {
			const { load, onChange } = failing(at);
			await vi.advanceTimersByTimeAsync(0);
			expect(load.phase).toBe('idle');
			await vi.advanceTimersByTimeAsync(120_000);
			expect(onChange).toHaveBeenCalledTimes(1);
		}
	);

	it.each(['metadata', 'data'] as const)(
		'calls no one after a dispose, from a failure of its %s',
		async (at) => {
			const { load, onChange } = failing(at);
			await vi.advanceTimersByTimeAsync(0);
			expect(vi.getTimerCount()).toBe(1);
			load.dispose();
			expect(vi.getTimerCount()).toBe(0);
			await vi.advanceTimersByTimeAsync(120_000);
			expect(onChange).not.toHaveBeenCalled();
		}
	);
});
