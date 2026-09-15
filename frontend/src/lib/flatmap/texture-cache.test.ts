import { afterEach, describe, expect, it, vi } from 'vitest';
import { acquireBitmap, clearTextureCache, releaseBitmap, textureKey } from './texture-cache';

/** A decoded picture, as much of one as the store reads. */
function fakeBitmap(width: number, closed: { count: number }): ImageBitmap {
	return {
		width,
		height: width / 2,
		close: () => closed.count++
	} as unknown as ImageBitmap;
}

/** Count the fetches and the decodes, and report what width was asked for. */
function stubDecoding(closed: { count: number }) {
	const fetches: string[] = [];
	const widths: (number | undefined)[] = [];
	vi.stubGlobal('fetch', async (url: string) => {
		fetches.push(url);
		return { ok: true, blob: async () => ({}) } as unknown as Response;
	});
	vi.stubGlobal('createImageBitmap', async (_blob: unknown, options?: { resizeWidth?: number }) => {
		widths.push(options?.resizeWidth);
		return fakeBitmap(options?.resizeWidth ?? 16383, closed);
	});
	return { fetches, widths };
}

afterEach(() => {
	clearTextureCache();
	vi.unstubAllGlobals();
});

describe('the shared picture store', () => {
	it('decodes a picture one time for every map that asks', async () => {
		const closed = { count: 0 };
		const { fetches } = stubDecoding(closed);
		const held = await Promise.all([
			acquireBitmap('/moon.webp', 4096),
			acquireBitmap('/moon.webp', 4096),
			acquireBitmap('/moon.webp', 4096)
		]);
		expect(fetches).toEqual(['/moon.webp']);
		expect(new Set(held.map((h) => h?.bitmap)).size).toBe(1);
		// The maps that waited on one decode share one picture. It stays open.
		expect(closed.count).toBe(0);
	});

	it('decodes to the width that was asked for', async () => {
		const closed = { count: 0 };
		const { widths } = stubDecoding(closed);
		const held = await acquireBitmap('/moon.webp', 4096);
		expect(widths).toEqual([4096]);
		expect(held?.bitmap.width).toBe(4096);
	});

	it('files each width as its own picture', async () => {
		const closed = { count: 0 };
		const { fetches } = stubDecoding(closed);
		const small = await acquireBitmap('/moon.webp', 1024);
		const large = await acquireBitmap('/moon.webp', 4096);
		expect(fetches.length).toBe(2);
		expect(small?.key).not.toBe(large?.key);
		expect(textureKey('/moon.webp', 1024)).toBe(small?.key);
	});

	it('keeps a picture while one map still claims it', async () => {
		const closed = { count: 0 };
		stubDecoding(closed);
		const first = await acquireBitmap('/moon.webp', 4096);
		const second = await acquireBitmap('/moon.webp', 4096);
		releaseBitmap(first!.key);
		expect(closed.count).toBe(0);
		releaseBitmap(second!.key);
	});

	it('drops unclaimed pictures that go past the budget', async () => {
		const closed = { count: 0 };
		stubDecoding(closed);
		// One picture of this width is already more than the budget of the
		// smallest machine.
		const held = await acquireBitmap('/moon.webp', 16383);
		releaseBitmap(held!.key);
		expect(closed.count).toBe(1);
	});
});
