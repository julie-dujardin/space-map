import { describe, it, expect } from 'vitest';
import { ChunkWindow } from '$lib/fetch/position/chunk-window';

interface TestParams {
	chunks: number;
	chunk_days: number;
	start_jd: number;
	/** Which indices have a file, by index. */
	present: boolean[];
}

const ZONE = 'test/zone';
const START_JD = 2450000;

/** Window over chunks that never resolve until `settle` is called, so a test
 *  can observe the state between the request and the store. */
class TestWindow extends ChunkWindow<{ idx: number }, TestParams> {
	readonly requested: string[] = [];
	private pending: (() => void)[] = [];

	protected isLoadable(params: TestParams, chunkIdx: number): boolean {
		return params.present[chunkIdx] ?? false;
	}

	protected fetchChunk(
		zone: string,
		_params: TestParams,
		chunkIdx: number,
		priority: RequestPriority
	): Promise<{ idx: number }> {
		this.requested.push(`${zone}:${chunkIdx}:${priority}`);
		return new Promise((resolve) => this.pending.push(() => resolve({ idx: chunkIdx })));
	}

	protected afterStore(): void {}

	settle(): void {
		const jobs = this.pending;
		this.pending = [];
		for (const job of jobs) job();
	}
}

function windowOf(present: boolean[]): TestWindow {
	return new TestWindow(
		new Map([[ZONE, { chunks: present.length, chunk_days: 10, start_jd: START_JD, present }]])
	);
}

/** Drain the microtask queue so the neighbour tail and awaited `done` land. */
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('ChunkWindow.ensure', () => {
	it('makes a repeat call on the same jd wait for the first call’s fetches', async () => {
		const win = windowOf([true, true, true]);
		const first = win.ensure(START_JD + 5);
		expect(first.ready).toBe(false);
		const second = win.ensure(START_JD + 5);
		expect(second.ready).toBe(false);
		let settled = false;
		void second.done.then(() => {
			settled = true;
		});
		await flush();
		// The chunk is still in flight: a second awaiter must not be told it can
		// query the store.
		expect(settled).toBe(false);
		win.settle();
		await second.done;
		expect(settled).toBe(true);
		expect(win.ensure(START_JD + 5).ready).toBe(true);
	});

	it('warms neighbours only once the current chunk has landed', async () => {
		const win = windowOf([true, true, true]);
		const { done } = win.ensure(START_JD + 15);
		expect(win.requested).toEqual([`${ZONE}:1:high`]);
		win.settle();
		await done;
		await flush();
		expect(win.requested).toEqual([`${ZONE}:1:high`, `${ZONE}:0:low`, `${ZONE}:2:low`]);
	});

	it('skips indices with no file and reports ready without them', async () => {
		const win = windowOf([false, false, true]);
		const { ready, done } = win.ensure(START_JD + 15);
		// Nothing to fetch for the current chunk, so the caller can query at once.
		expect(ready).toBe(true);
		await done;
		await flush();
		expect(win.requested).toEqual([`${ZONE}:2:low`]);
	});
});
