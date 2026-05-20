import type { PositionedBody } from '$lib/types/objects';
import type { Vec3 } from '$lib/scene/animation/math';
import OrbitWorker from './worker?worker';
import { packBodies, columnsTransferList } from './soa';

/*
 * OrbitWorkerPool — offloads per-frame Kepler solves for asteroid zone and
 * spacecraft point clouds to a fixed-size worker pool.
 *
 * Protocol (see {@link './worker.ts'}):
 *   - rewireOne / unwireOne: ship one group's SoA element columns to its
 *     assigned worker, or drop a group. Called per-zone whenever the
 *     ContextManager dirty markers say a group's bodies or skip-set changed.
 *   - tick: per frame, sends the current jd, basis, and each group's parent
 *     position; the worker writes basis-relative Float32 positions into a
 *     pre-allocated back-buffer and transfers it back. On result the buffer
 *     becomes the new front (bound to geometry); old front becomes the new
 *     back. The caller rebinds the geometry attribute to the new front via
 *     the {@link setResultHandler} callback.
 *
 * Double-buffering: each group holds one back-buffer; while the worker is
 * processing, back is null and the group is skipped on that frame's tick.
 */

interface GroupState {
	workerIdx: number;
	capacity: number;
	/** Array currently bound to the geometry's position attribute. */
	front: Float32Array;
	/** Free array the next tick will send to the worker, or null if in flight. */
	back: Float32Array | null;
	count: number;
	/** Basis passed to the worker at dispatch of the in-flight tick (if any). */
	pendingBasis: Vec3 | null;
	/** Parent position passed to the worker at dispatch of the in-flight tick. */
	pendingParent: Vec3 | null;
	/** Basis that the current `front` buffer was computed under. */
	frontBasis: Vec3;
	/** Parent position that the current `front` buffer was computed under. */
	frontParent: Vec3;
}

export type GroupResultHandler = (
	id: string,
	positions: Float32Array,
	count: number,
	basis: Vec3,
	parent: Vec3
) => void;

type TickResult = {
	type: 'tickResult';
	groups: { id: string; count: number; buf: ArrayBufferLike }[];
};

export class OrbitWorkerPool {
	private workers: Worker[];
	private groups = new Map<string, GroupState>();
	private onResult: GroupResultHandler | null = null;
	private nextWorker = 0;

	constructor(size: number = navigator.hardwareConcurrency ?? 4) {
		const n = Math.max(1, Math.min(8, size - 1));
		this.workers = [];
		for (let i = 0; i < n; i++) {
			const w = new OrbitWorker();
			w.onmessage = (ev: MessageEvent<TickResult>) => this.onMessage(ev.data);
			this.workers.push(w);
		}
	}

	setResultHandler(handler: GroupResultHandler): void {
		this.onResult = handler;
	}

	get workerCount(): number {
		return this.workers.length;
	}

	get groupCount(): number {
		return this.groups.size;
	}

	/**
	 * Return the current front-buffer for a group. Caller binds this to the
	 * geometry's position attribute after calling {@link rewire}.
	 */
	front(id: string): Float32Array | undefined {
		return this.groups.get(id)?.front;
	}

	/**
	 * Add or replace one group's SoA element columns. Empty bodies → unwire
	 * (drops geometry binding upstream).
	 *
	 * Reuses the previous front buffer whenever capacity matches — even if a
	 * tick is currently in flight (prev.back === null). Allocating a fresh
	 * zero-filled front here would make the geometry blank out between
	 * rewire and the next worker result, which at high time rates (frequent
	 * rebases triggering rewires) reads as constant cloud-flicker.
	 *
	 * We do NOT allocate a fresh back when one is in flight: doing so would
	 * let a new tick dispatch before the old one returns, and the old
	 * result would then be paired with the new dispatch's pendingBasis /
	 * pendingParent in onMessage — placing the cloud at a wrong location.
	 * Letting back stay null defers the next dispatch until the in-flight
	 * tick lands naturally.
	 */
	rewireOne(id: string, bodies: PositionedBody[], skip: Set<string>): void {
		if (bodies.length === 0) {
			this.unwireOne(id);
			return;
		}
		const prev = this.groups.get(id);
		const workerIdx = prev?.workerIdx ?? this.nextWorker++ % this.workers.length;
		const capacity = bodies.length;

		let front: Float32Array;
		let back: Float32Array | null;
		if (prev && prev.capacity === capacity) {
			front = prev.front;
			back = prev.back;
		} else {
			front = new Float32Array(capacity * 3);
			back = new Float32Array(capacity * 3);
			if (prev) {
				const n = Math.min(prev.front.length, front.length);
				front.set(prev.front.subarray(0, n));
			}
		}

		const cols = packBodies(bodies, skip);
		// If a tick is in flight (prev.back === null), preserve its pending
		// dispatch state so the returning result is paired with the basis /
		// parent it was actually computed under — see comment above re: back.
		const inFlight = !!prev && prev.back === null;
		this.groups.set(id, {
			workerIdx,
			capacity,
			front,
			back,
			count: prev?.count ?? capacity,
			pendingBasis: inFlight ? prev!.pendingBasis : null,
			pendingParent: inFlight ? prev!.pendingParent : null,
			frontBasis: prev?.frontBasis ?? [0, 0, 0],
			frontParent: prev?.frontParent ?? [0, 0, 0]
		});

		this.workers[workerIdx].postMessage(
			{ type: 'rewireDelta', set: [{ id, cols }] },
			columnsTransferList(cols)
		);
	}

	/** Drop one group locally and tell its worker to forget it. No-op if unknown. */
	unwireOne(id: string): void {
		const prev = this.groups.get(id);
		if (!prev) return;
		this.groups.delete(id);
		this.workers[prev.workerIdx].postMessage({
			type: 'rewireDelta',
			set: [],
			remove: [id]
		});
	}

	/**
	 * Per-frame dispatch. Groups with no free back-buffer (worker still chewing
	 * on last tick) are skipped this frame — they'll catch up on the next one.
	 */
	tick(jd: number, basis: Vec3, parents: Map<string, Vec3>): void {
		const perWorker: {
			id: string;
			parent: [number, number, number];
			out: Float32Array;
		}[][] = this.workers.map(() => []);

		for (const [id, state] of this.groups) {
			if (!state.back) continue;
			const parent = parents.get(id) ?? ([0, 0, 0] as Vec3);
			perWorker[state.workerIdx].push({
				id,
				parent: [parent[0], parent[1], parent[2]],
				out: state.back
			});
			state.back = null;
			state.pendingBasis = [basis[0], basis[1], basis[2]];
			state.pendingParent = [parent[0], parent[1], parent[2]];
		}

		for (let i = 0; i < this.workers.length; i++) {
			const groupMsgs = perWorker[i];
			if (groupMsgs.length === 0) continue;
			const transfers: Transferable[] = groupMsgs.map((g) => g.out.buffer as Transferable);
			this.workers[i].postMessage(
				{ type: 'tick', jd, basis: [basis[0], basis[1], basis[2]], groups: groupMsgs },
				transfers
			);
		}
	}

	private onMessage(msg: TickResult): void {
		if (msg.type !== 'tickResult') return;
		for (const g of msg.groups) {
			const state = this.groups.get(g.id);
			if (!state) continue;
			const returned = new Float32Array(g.buf);
			const oldFront = state.front;
			state.front = returned;
			state.back = oldFront;
			state.count = g.count;
			const basis = state.pendingBasis ?? state.frontBasis;
			const parent = state.pendingParent ?? state.frontParent;
			state.frontBasis = basis;
			state.frontParent = parent;
			state.pendingBasis = null;
			state.pendingParent = null;
			this.onResult?.(g.id, returned, g.count, basis, parent);
		}
	}

	destroy(): void {
		for (const w of this.workers) w.terminate();
		this.workers.length = 0;
		this.groups.clear();
	}
}
