/**
 * Main-thread handle on the travel worker.
 *
 * Only the newest request matters — the UI asks again whenever the destination,
 * vehicle or arrival mode changes — so earlier ones resolve to null rather than
 * racing to overwrite the display. Callers can ignore a null and keep whatever
 * they were showing.
 */

import type { TravelBody } from './body';
import { computePorkchop, selectRoutes, type PorkchopOptions } from './porkchop';
import type { TravelRequest, TravelResponse } from './worker';

export interface SolveResult {
	grid: import('./porkchop').PorkchopGrid;
	routes: import('./porkchop').RouteChoice[];
}

export class TravelSolver {
	#worker: Worker | null = null;
	#nextId = 1;
	#latestId = 0;
	#pending = new Map<number, (result: SolveResult | null) => void>();

	/** Spawned on first use so the module costs nothing until a route is asked for. */
	#ensureWorker(): Worker | null {
		if (this.#worker) return this.#worker;
		if (typeof Worker === 'undefined') return null;
		const worker = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' });
		worker.onmessage = (ev: MessageEvent<TravelResponse>) => {
			const { id, grid, routes } = ev.data;
			const resolve = this.#pending.get(id);
			this.#pending.delete(id);
			resolve?.(id === this.#latestId ? { grid, routes } : null);
		};
		this.#worker = worker;
		return worker;
	}

	/**
	 * Solve a grid and pick routes. Resolves to null when a newer request has
	 * already been made, or when the solve failed.
	 */
	solve(
		departure: TravelBody,
		target: TravelBody,
		options: PorkchopOptions
	): Promise<SolveResult | null> {
		const worker = this.#ensureWorker();
		if (!worker) {
			// No worker available (SSR, or a browser without module workers) —
			// solving inline is slower but keeps the feature working.
			const grid = computePorkchop(departure, target, options);
			return Promise.resolve({ grid, routes: selectRoutes(grid, departure, target, options) });
		}

		const id = this.#nextId++;
		this.#latestId = id;
		const request: TravelRequest = { type: 'solve', id, departure, target, options };
		return new Promise<SolveResult | null>((resolve) => {
			this.#pending.set(id, resolve);
			worker.postMessage(request);
		});
	}

	/** Drop the worker and settle anything still outstanding. */
	dispose(): void {
		this.#worker?.terminate();
		this.#worker = null;
		for (const resolve of this.#pending.values()) resolve(null);
		this.#pending.clear();
	}
}
