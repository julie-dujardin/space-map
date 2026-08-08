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

/** A request in flight, and how to answer it without the worker. */
interface Pending {
	resolve: (result: SolveResult | null) => void;
	inline: () => SolveResult;
}

function solveInline(
	departure: TravelBody,
	target: TravelBody,
	options: PorkchopOptions
): SolveResult {
	const grid = computePorkchop(departure, target, options);
	return { grid, routes: selectRoutes(grid, departure, target, options) };
}

export class TravelSolver {
	#worker: Worker | null = null;
	#nextId = 1;
	#latestId = 0;
	#pending = new Map<number, Pending>();

	/** Spawned on first use so the module costs nothing until a route is asked for. */
	#ensureWorker(): Worker | null {
		if (this.#worker) return this.#worker;
		if (typeof Worker === 'undefined') return null;
		const worker = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' });
		worker.onmessage = (ev: MessageEvent<TravelResponse>) => {
			const { id, grid, routes } = ev.data;
			const pending = this.#pending.get(id);
			this.#pending.delete(id);
			pending?.resolve(id === this.#latestId ? { grid, routes } : null);
		};
		// A worker that dies takes every outstanding answer with it, and the panel
		// would sit on "finding routes" for the rest of the session. Solve what is
		// still wanted here instead, and let the next request spawn a fresh one.
		worker.onerror = (ev) => this.#fallBack(`worker error: ${ev.message || 'unknown'}`);
		worker.onmessageerror = () => this.#fallBack('worker sent a message that could not be read');
		this.#worker = worker;
		return worker;
	}

	#fallBack(reason: string): void {
		console.error(`[travel] ${reason} — solving on the main thread instead.`);
		this.#worker?.terminate();
		this.#worker = null;
		const outstanding = [...this.#pending.entries()];
		this.#pending.clear();
		for (const [id, pending] of outstanding) {
			pending.resolve(id === this.#latestId ? pending.inline() : null);
		}
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
		const inline = () => solveInline(departure, target, options);
		const worker = this.#ensureWorker();
		// No worker available (SSR, or a browser without module workers) — solving
		// here is slower but keeps the feature working.
		if (!worker) return Promise.resolve(inline());

		const id = this.#nextId++;
		this.#latestId = id;
		const request: TravelRequest = { type: 'solve', id, departure, target, options };
		return new Promise<SolveResult | null>((resolve) => {
			this.#pending.set(id, { resolve, inline });
			worker.postMessage(request);
		});
	}

	/** Drop the worker and settle anything still outstanding. */
	dispose(): void {
		this.#worker?.terminate();
		this.#worker = null;
		for (const pending of this.#pending.values()) pending.resolve(null);
		this.#pending.clear();
	}
}
