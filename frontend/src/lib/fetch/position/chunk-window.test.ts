import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
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
	private failing: (() => void)[] = [];

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
		return new Promise((resolve, reject) => {
			this.pending.push(() => resolve({ idx: chunkIdx }));
			this.failing.push(() => reject(new Error(`no chunk ${chunkIdx}`)));
		});
	}

	/** Fail every fetch in flight. */
	fail(): void {
		const jobs = this.failing;
		this.pending = [];
		this.failing = [];
		for (const job of jobs) job();
	}

	protected afterStore(): void {}

	settle(): void {
		const jobs = this.pending;
		this.pending = [];
		this.failing = [];
		for (const job of jobs) job();
	}

	holds(chunkIdx: number): boolean {
		return this.isResident(ZONE, chunkIdx);
	}
}

function windowOf(present: boolean[]): TestWindow {
	return new TestWindow(
		new Map([[ZONE, { chunks: present.length, chunk_days: 10, start_jd: START_JD, present }]])
	);
}

/** Drain the microtask queue so the neighbour tail and awaited `done` land. */
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('ChunkWindow.loadingAt', () => {
	it('is true from the request for a chunk to its arrival', async () => {
		const win = windowOf([true, true, true]);
		expect(win.loadingAt(START_JD + 5)).toBe(false);
		const done = win.load(START_JD + 5);
		expect(win.loadingAt(START_JD + 5)).toBe(true);
		expect(win.loadingAt(START_JD + 5, ZONE)).toBe(true);
		expect(win.loadingAt(START_JD + 5, 'other/zone')).toBe(false);
		// The chunk of another date is not on its way.
		expect(win.loadingAt(START_JD + 25)).toBe(false);
		win.settle();
		await done;
		expect(win.loadingAt(START_JD + 5)).toBe(false);
	});

	it('is false for a date with no file', () => {
		const win = windowOf([true, false, true]);
		win.ensure(START_JD + 15);
		expect(win.loadingAt(START_JD + 15)).toBe(false);
	});
});

describe('ChunkWindow.request', () => {
	it('loads the chunk for a date and keeps the chunks of the window', async () => {
		const win = windowOf(Array(8).fill(true));
		win.ensure(START_JD + 5);
		win.settle();
		await flush();
		win.request(START_JD + 65);
		expect(win.loadingAt(START_JD + 65)).toBe(true);
		win.settle();
		await flush();
		expect(win.loadingAt(START_JD + 65)).toBe(false);
		expect(win.holds(0)).toBe(true);
		expect(win.holds(6)).toBe(true);
		// The window moves with the next `ensure`.
		win.ensure(START_JD + 65);
		expect(win.holds(0)).toBe(false);
		expect(win.holds(6)).toBe(true);
	});

	it('asks for nothing where no file is', () => {
		const win = windowOf([true, false]);
		win.request(START_JD + 15);
		expect(win.requested).toEqual([]);
	});
});

describe('ChunkWindow.load', () => {
	it('makes a repeat call on the same jd wait for the first call’s fetches', async () => {
		const win = windowOf([true, true, true]);
		win.ensure(START_JD + 5);
		let settled = false;
		const second = win.load(START_JD + 5).then(() => {
			settled = true;
		});
		await flush();
		// The chunk is still in flight: a second awaiter must not be told it can
		// query the store.
		expect(settled).toBe(false);
		expect(win.requested).toEqual([`${ZONE}:0:high`]);
		win.settle();
		await second;
		expect(win.holds(0)).toBe(true);
	});

	it('warms neighbours only once the current chunk has landed', async () => {
		const win = windowOf([true, true, true]);
		const done = win.load(START_JD + 15);
		expect(win.requested).toEqual([`${ZONE}:1:high`]);
		win.settle();
		await done;
		await flush();
		expect(win.requested).toEqual([`${ZONE}:1:high`, `${ZONE}:0:low`, `${ZONE}:2:low`]);
	});

	it('skips indices with no file and resolves without them', async () => {
		const win = windowOf([false, false, true]);
		// Nothing to fetch for the current chunk, so the caller can query at once.
		await win.load(START_JD + 15);
		await flush();
		expect(win.requested).toEqual([`${ZONE}:2:low`]);
	});
});

describe('ChunkWindow after a failed load', () => {
	/** Past the longest first wait, jitter included. */
	const FIRST_WAIT_MS = 2500;

	beforeEach(() => {
		vi.useFakeTimers();
	});
	afterEach(() => {
		vi.useRealTimers();
	});

	/** One chunk, asked for and failed. */
	async function failedWindow(): Promise<TestWindow> {
		const win = windowOf([true]);
		const done = win.load(START_JD + 5);
		win.fail();
		await expect(done).rejects.toThrow('no chunk 0');
		return win;
	}

	it('does not ask again while the clock runs, till the wait is over', async () => {
		const win = await failedWindow();
		// A frame loop: a new jd on every call.
		for (let frame = 1; frame <= 100; frame++) win.ensure(START_JD + 5 + frame * 1e-6);
		expect(win.requested).toEqual([`${ZONE}:0:high`]);
		await vi.advanceTimersByTimeAsync(FIRST_WAIT_MS);
		win.ensure(START_JD + 6);
		expect(win.requested).toEqual([`${ZONE}:0:high`, `${ZONE}:0:high`]);
	});

	it('asks again for a clock that stands still, once the wait is over', async () => {
		const win = await failedWindow();
		const version = win.version;
		win.ensure(START_JD + 5);
		expect(win.requested).toHaveLength(1);
		await vi.advanceTimersByTimeAsync(FIRST_WAIT_MS);
		// What brings the renderer back to a date it has already placed.
		expect(win.version).toBe(version + 1);
		win.ensure(START_JD + 5);
		expect(win.requested).toHaveLength(2);
		// One time: the chunk is in flight.
		win.ensure(START_JD + 5);
		expect(win.requested).toHaveLength(2);
	});

	it('says what failed, for a loop that reads no outcome', async () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		await failedWindow();
		expect(warn).toHaveBeenCalledWith(
			`[position] chunk ${ZONE}:0 did not load:`,
			expect.objectContaining({ message: 'no chunk 0' })
		);
		warn.mockRestore();
	});

	it('still awaits the chunk through its wait and its next try', async () => {
		const win = await failedWindow();
		// Not on its way, and not for good either.
		expect(win.loadingAt(START_JD + 5)).toBe(false);
		expect(win.awaitedAt(START_JD + 5)).toBe(true);
		expect(win.awaitedAt(START_JD + 5, 'other/zone')).toBe(false);
		await vi.advanceTimersByTimeAsync(FIRST_WAIT_MS);
		win.ensure(START_JD + 5);
		expect(win.awaitedAt(START_JD + 5)).toBe(true);
		win.settle();
		await vi.advanceTimersByTimeAsync(0);
		expect(win.awaitedAt(START_JD + 5)).toBe(false);
	});

	it('asks at once for a scene that holds its date on the chunk', async () => {
		const win = await failedWindow();
		win.request(START_JD + 5);
		expect(win.requested).toHaveLength(2);
		expect(win.loadingAt(START_JD + 5)).toBe(true);
	});

	it('asks at once for a caller that waits, and is not loading the chunk till then', async () => {
		const win = await failedWindow();
		expect(win.loadingAt(START_JD + 5)).toBe(false);
		const again = win.load(START_JD + 5);
		expect(win.requested).toHaveLength(2);
		win.settle();
		await again;
		expect(win.holds(0)).toBe(true);
	});

	it('waits longer after each failure in a row', async () => {
		const win = await failedWindow();
		await vi.advanceTimersByTimeAsync(FIRST_WAIT_MS);
		win.ensure(START_JD + 5);
		win.fail();
		await vi.advanceTimersByTimeAsync(FIRST_WAIT_MS);
		// The second wait is twice the first.
		win.ensure(START_JD + 5);
		expect(win.requested).toHaveLength(2);
		await vi.advanceTimersByTimeAsync(FIRST_WAIT_MS);
		win.ensure(START_JD + 5);
		expect(win.requested).toHaveLength(3);
	});
});
