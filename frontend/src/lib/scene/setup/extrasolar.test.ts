import { describe, expect, it, vi } from 'vitest';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { PositionedBody } from '$lib/types/objects';
import { ensureExtrasolarBody } from './extrasolar';

const { lookup, makeStarBody } = vi.hoisted(() => ({
	lookup: vi.fn(),
	makeStarBody: vi.fn((record: { id: number }) => ({
		data: { id: `x-${record.id}` },
		extrasolar: { record }
	}))
}));
vi.mock('$lib/fetch/extrasolar/lookup', () => ({ extrasolarLookup: { lookup } }));
vi.mock('$lib/scene/focus/star-focus', () => ({ makeStarBody }));

describe('ensureExtrasolarBody', () => {
	it('keeps one body for a star asked for twice at once', async () => {
		lookup.mockResolvedValue({ kind: 'live', record: { id: 7, metadata: {} } });
		const kept = new Map<string, PositionedBody>();
		const ctx = {
			getBody: (id: string) => kept.get(id),
			bodies: {
				addExtrasolar: (body: PositionedBody) => kept.set(body.data.id, body)
			}
		} as unknown as ContextManager;
		await Promise.all([ensureExtrasolarBody(ctx, 'x-7'), ensureExtrasolarBody(ctx, 'x-7')]);
		expect(makeStarBody).toHaveBeenCalledTimes(1);
		expect(kept.size).toBe(1);
	});
});
