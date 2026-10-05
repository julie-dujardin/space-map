import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

/** Whether freshly-spawned workers answer a ping. Flipped per test to stand in
 *  for the mobile OS killing a backgrounded tab's workers. */
let workersAlive = true;
const spawned: FakeWorker[] = [];

/** Worker stub that ponges on a macrotask when alive and stays silent when not.
 *  Ticks are held in `ticks` for a test to answer or drop. */
class FakeWorker {
	onmessage: ((ev: { data: unknown }) => void) | null = null;
	onerror: ((ev: { message: string }) => void) | null = null;
	terminated = false;
	readonly alive = workersAlive;
	ticks: { groups: { id: string; out: Float32Array; outIds: Uint8Array }[] }[] = [];
	constructor() {
		spawned.push(this);
	}
	postMessage(msg: { type: string }) {
		if (!this.alive || this.terminated) return;
		if (msg.type === 'tick') this.ticks.push(msg as unknown as FakeWorker['ticks'][number]);
		if (msg.type !== 'ping') return;
		setTimeout(() => this.onmessage?.({ data: { type: 'pong' } }), 0);
	}
	/** Answer every held tick, as a live worker would. */
	reply() {
		for (const t of this.ticks.splice(0)) {
			const groups = t.groups.map((g) => ({
				id: g.id,
				count: 0,
				buf: g.out.buffer,
				idbuf: g.outIds.buffer
			}));
			this.onmessage?.({ data: { type: 'tickResult', groups } });
		}
	}
	terminate() {
		this.terminated = true;
	}
}

vi.mock('./worker?worker&inline', () => ({ default: FakeWorker }));

const { OrbitWorkerPool } = await import('./pool');
const { allocColumns } = await import('./soa');

describe('OrbitWorkerPool liveness', () => {
	beforeEach(() => {
		workersAlive = true;
		spawned.length = 0;
	});

	it('joins a concurrent probe instead of failing it', async () => {
		const pool = new OrbitWorkerPool(2);
		const [a, b] = await Promise.all([pool.ping(500), pool.ping(500)]);
		expect([a, b]).toEqual([true, true]);
		pool.destroy();
	});

	it('reports dead workers once the timeout expires', async () => {
		workersAlive = false;
		const pool = new OrbitWorkerPool(2);
		expect(await pool.ping(20)).toBe(false);
		pool.destroy();
	});

	it('bumps the generation on respawn so a mid-flight rewire can redo itself', () => {
		const pool = new OrbitWorkerPool(2);
		const before = pool.poolGeneration;
		pool.respawn();
		expect(pool.poolGeneration).toBe(before + 1);
		expect(spawned.filter((w) => w.terminated)).toHaveLength(2);
		pool.destroy();
	});
});

describe('OrbitWorkerPool stall watchdog', () => {
	let now = 0;
	const parents = new Map([['g', [0, 0, 0] as [number, number, number]]]);

	beforeEach(() => {
		workersAlive = true;
		spawned.length = 0;
		now = 0;
		vi.spyOn(performance, 'now').mockImplementation(() => now);
	});
	afterEach(() => vi.restoreAllMocks());

	/** Tick every 16 ms for `ms` of frame time. */
	function run(pool: InstanceType<typeof OrbitWorkerPool>, ms: number) {
		for (let t = 0; t < ms; t += 16) {
			now += 16;
			pool.tick(0, [0, 0, 0], parents);
		}
	}

	function wired(onStall: () => void) {
		const pool = new OrbitWorkerPool(2);
		pool.setStallHandler(onStall);
		pool.rewireOneCols('g', allocColumns(4), 0);
		return pool;
	}

	it('reports a dispatch that never comes back', () => {
		const onStall = vi.fn();
		const pool = wired(onStall);
		run(pool, 4000);
		expect(onStall).not.toHaveBeenCalled();
		run(pool, 2000);
		expect(onStall).toHaveBeenCalledTimes(1);
		pool.destroy();
	});

	it('stays quiet while the worker keeps answering', () => {
		const onStall = vi.fn();
		const pool = wired(onStall);
		for (let i = 0; i < 600; i++) {
			run(pool, 16);
			spawned[0].reply();
		}
		expect(onStall).not.toHaveBeenCalled();
		pool.destroy();
	});

	it("doesn't age a dispatch across a hidden tab's pause", () => {
		const onStall = vi.fn();
		const pool = wired(onStall);
		run(pool, 16);
		now += 10 * 60_000;
		run(pool, 16);
		expect(onStall).not.toHaveBeenCalled();
		pool.destroy();
	});

	it('reports a worker error', () => {
		const onStall = vi.fn();
		const pool = wired(onStall);
		spawned[0].onerror?.({ message: 'boom' });
		expect(onStall).toHaveBeenCalledTimes(1);
		pool.destroy();
	});

	it("doesn't respawn in a loop when the new workers never answer", () => {
		const onStall = vi.fn();
		const pool = wired(onStall);
		pool.respawn();
		pool.rewireOneCols('g', allocColumns(4), 0);
		for (const w of spawned) w.onerror?.({ message: 'failed to load' });
		run(pool, 20_000);
		expect(onStall).not.toHaveBeenCalled();
		pool.destroy();
	});
});
