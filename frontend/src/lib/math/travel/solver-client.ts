/**
 * Main-thread handle on the travel workers.
 *
 * Only the newest request of each kind matters — the UI asks again whenever the
 * destination, vehicle or arrival mode changes — so earlier ones resolve to null
 * rather than racing to overwrite the display. Callers can ignore a null and
 * keep whatever they were showing.
 *
 * The two kinds get a worker each, and this is the load-bearing part: a worker
 * runs its messages one after another, and a swing-by hunt takes seconds where a
 * grid takes milliseconds. Sharing one would put every re-solve behind whatever
 * hunt happened to be running and leave the panel reading "finding routes" for
 * as long as it took.
 *
 * A superseded hunt is killed rather than waited out, for the same reason: it
 * has seconds of work left that nothing will ever read, and the request that
 * replaced it would queue behind all of it.
 */

import type { TravelBody } from './body';
import { findAssistRoute, type AssistOptions } from './assist';
import { computePorkchop, selectRoutes, type PorkchopOptions } from './porkchop';
import type { Route } from './route';
import type { TravelRequest, TravelResponse } from './worker';

export interface SolveResult {
	grid: import('./porkchop').PorkchopGrid;
	routes: import('./porkchop').RouteChoice[];
}

type RequestKind = 'solve' | 'assist';

/** A request in flight, and how to answer it without a worker. */
interface Pending {
	kind: RequestKind;
	/** Erased: the caller's promise carries the real type, and `#dispatch` is the
	 *  only place the two are tied together. */
	resolve: (result: unknown) => void;
	inline: () => unknown;
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
	#workers: Record<RequestKind, Worker | null> = { solve: null, assist: null };
	#nextId = 1;
	#latest: Record<RequestKind, number> = { solve: 0, assist: 0 };
	#pending = new Map<number, Pending>();

	/** Spawned on first use so the module costs nothing until a route is asked for. */
	#ensureWorker(kind: RequestKind): Worker | null {
		const existing = this.#workers[kind];
		if (existing) return existing;
		if (typeof Worker === 'undefined') return null;
		const worker = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' });
		worker.onmessage = (ev: MessageEvent<TravelResponse>) => {
			const msg = ev.data;
			const pending = this.#pending.get(msg.id);
			this.#pending.delete(msg.id);
			if (!pending) return;
			const superseded = msg.id !== this.#latest[pending.kind];
			const answer = msg.type === 'solved' ? { grid: msg.grid, routes: msg.routes } : msg.route;
			pending.resolve(superseded ? null : answer);
		};
		// A worker that dies takes every outstanding answer with it, and the panel
		// would sit on "finding routes" for the rest of the session. Solve what is
		// still wanted here instead, and let the next request spawn a fresh one.
		worker.onerror = (ev) => this.#fallBack(kind, `worker error: ${ev.message || 'unknown'}`);
		worker.onmessageerror = () =>
			this.#fallBack(kind, 'worker sent a message that could not be read');
		this.#workers[kind] = worker;
		return worker;
	}

	#fallBack(kind: RequestKind, reason: string): void {
		console.error(`[travel] ${reason} — solving on the main thread instead.`);
		this.#stop(kind);
		for (const [id, pending] of this.#take(kind)) {
			pending.resolve(id === this.#latest[kind] ? pending.inline() : null);
		}
	}

	/** Stop that worker and settle whatever it still owed, as superseded. */
	#discard(kind: RequestKind): void {
		this.#stop(kind);
		for (const [, pending] of this.#take(kind)) pending.resolve(null);
	}

	#stop(kind: RequestKind): void {
		this.#workers[kind]?.terminate();
		this.#workers[kind] = null;
	}

	/** Remove and return everything outstanding for one kind. */
	#take(kind: RequestKind): [number, Pending][] {
		const taken = [...this.#pending].filter(([, pending]) => pending.kind === kind);
		for (const [id] of taken) this.#pending.delete(id);
		return taken;
	}

	#dispatch<T>(
		kind: RequestKind,
		build: (id: number) => TravelRequest,
		inline: () => T,
		restart = false
	) {
		// A hunt already running is work for a question nobody is asking any more.
		if (restart && this.#workers[kind]) this.#discard(kind);
		const worker = this.#ensureWorker(kind);
		// No worker available (SSR, or a browser without module workers) — solving
		// here is slower but keeps the feature working.
		if (!worker) return Promise.resolve(inline());

		const id = this.#nextId++;
		this.#latest[kind] = id;
		return new Promise<T | null>((resolve) => {
			this.#pending.set(id, { kind, resolve: resolve as (result: unknown) => void, inline });
			worker.postMessage(build(id));
		});
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
		return this.#dispatch(
			'solve',
			(id) => ({ type: 'solve', id, departure, target, options }),
			() => solveInline(departure, target, options)
		);
	}

	/**
	 * Hunt for the cheapest route that swings past one of `vias`. Resolves to null
	 * when a newer request has been made, or when there is no such route.
	 *
	 * Seconds rather than milliseconds, so callers should show the direct answer
	 * first and let this fill in behind it.
	 */
	findAssist(
		departure: TravelBody,
		target: TravelBody,
		vias: TravelBody[],
		options: AssistOptions
	): Promise<Route | null> {
		return this.#dispatch(
			'assist',
			(id) => ({ type: 'assist', id, departure, target, vias, options }),
			() => findAssistRoute(departure, target, vias, options),
			true
		);
	}

	/** Drop the workers and settle anything still outstanding. */
	dispose(): void {
		this.#discard('solve');
		this.#discard('assist');
	}
}
