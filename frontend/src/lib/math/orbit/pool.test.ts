import { describe, it, expect, vi, beforeEach } from 'vitest';

/** Whether freshly-spawned workers answer a ping. Flipped per test to stand in
 *  for the mobile OS killing a backgrounded tab's workers. */
let workersAlive = true;
const spawned: FakeWorker[] = [];

/** Worker stub that ponges on a macrotask when alive and stays silent when not. */
class FakeWorker {
	onmessage: ((ev: { data: unknown }) => void) | null = null;
	terminated = false;
	readonly alive = workersAlive;
	constructor() {
		spawned.push(this);
	}
	postMessage(msg: { type: string }) {
		if (msg.type !== 'ping' || !this.alive || this.terminated) return;
		setTimeout(() => this.onmessage?.({ data: { type: 'pong' } }), 0);
	}
	terminate() {
		this.terminated = true;
	}
}

vi.mock('./worker?worker', () => ({ default: FakeWorker }));

const { OrbitWorkerPool } = await import('./pool');

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
