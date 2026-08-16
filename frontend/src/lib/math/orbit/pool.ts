import type { PositionedBody } from '$lib/types/objects';
import type { Vec3 } from '$lib/scene/animation/math';
import OrbitWorker from './worker?worker';
import { packBodiesSliced, columnsTransferList, type OrbitColumns } from './soa';

/*
 * OrbitWorkerPool — offloads per-frame Kepler solves for asteroid zone and
 * spacecraft point clouds to a fixed-size worker pool (see {@link './worker.ts'}).
 *
 * rewireOne/unwireOne ship or drop a group's SoA columns on its assigned
 * worker when ContextManager dirty markers fire. tick sends jd/basis/parent
 * per group; each worker writes into a pre-allocated back-buffer, which
 * becomes the new front (bound to geometry) on return via {@link setResultHandler}.
 *
 * Double-buffered: while a group's worker is busy, back is null and that
 * group is skipped on the frame's tick.
 */

interface GroupState {
	workerIdx: number;
	capacity: number;
	/** Array currently bound to the geometry's position attribute. */
	front: Float32Array;
	/** Free array the next tick will send to the worker, or null if in flight. */
	back: Float32Array | null;
	/** Pick-id bytes (RGBA per point) paired with `front`; ping-ponged in lockstep. */
	idFront: Uint8Array;
	idBack: Uint8Array | null;
	count: number;
	/** Basis passed to the worker at dispatch of the in-flight tick (if any). */
	pendingBasis: Vec3 | null;
	/** Parent position passed to the worker at dispatch of the in-flight tick. */
	pendingParent: Vec3 | null;
	/** jd passed to the worker at dispatch of the in-flight tick. */
	pendingJd: number | null;
	/** Basis that the current `front` buffer was computed under. */
	frontBasis: Vec3;
	/** Parent position that the current `front` buffer was computed under. */
	frontParent: Vec3;
	/** jd that the current `front` buffer was solved at — lets the caller's
	 *  subpixel gate measure how stale a skipped group's positions are. */
	frontJd: number;
}

export type GroupResultHandler = (
	id: string,
	positions: Float32Array,
	count: number,
	basis: Vec3,
	parent: Vec3,
	jd: number,
	pickIds: Uint8Array
) => void;

type TickResult = {
	type: 'tickResult';
	groups: { id: string; count: number; buf: ArrayBufferLike; idbuf: ArrayBufferLike }[];
};

type PoolInMsg = TickResult | { type: 'pong' };

export class OrbitWorkerPool {
	private workers: Worker[] = [];
	private groups = new Map<string, GroupState>();
	private onResult: GroupResultHandler | null = null;
	private readonly size: number;
	/** In-flight liveness probe; resolves once every worker has ponged. */
	private pendingPing: { need: number; got: number; resolve: (ok: boolean) => void } | null = null;

	constructor(size: number = navigator.hardwareConcurrency ?? 4) {
		// Floor at 2 so even 2-core phones (hardwareConcurrency=2) get parallel
		// asteroid/spacecraft propagation; double-buffer absorbs any UI-thread
		// contention, so reserving a core for UI no longer earns its keep.
		this.size = Math.max(2, Math.min(8, size));
		this.spawn();
	}

	private spawn(): void {
		for (let i = 0; i < this.size; i++) {
			const w = new OrbitWorker();
			w.onmessage = (ev: MessageEvent<PoolInMsg>) => this.onMessage(ev.data);
			this.workers.push(w);
		}
	}

	/**
	 * True once every worker answers within `timeoutMs`. A backgrounded tab's
	 * workers can be killed by the mobile OS yet still look alive on the main
	 * thread — a timeout is the only signal they're dead.
	 */
	ping(timeoutMs = 800): Promise<boolean> {
		if (this.workers.length === 0) return Promise.resolve(false);
		this.pendingPing?.resolve(false);
		return new Promise<boolean>((resolve) => {
			// Guard by identity so a superseded or already-resolved probe no-ops;
			// lets the dangling timer expire without a clearTimeout.
			const state = {
				need: this.workers.length,
				got: 0,
				resolve: (ok: boolean) => {
					if (this.pendingPing !== state) return;
					this.pendingPing = null;
					resolve(ok);
				}
			};
			this.pendingPing = state;
			setTimeout(() => state.resolve(false), timeoutMs);
			for (const w of this.workers) w.postMessage({ type: 'ping' });
		});
	}

	/**
	 * Recreate the pool after a worker death. Wiring is dropped — in-flight
	 * back-buffers went to the dead workers — so the caller must re-wire.
	 */
	respawn(): void {
		this.pendingPing?.resolve(false);
		for (const w of this.workers) w.terminate();
		this.workers = [];
		this.groups.clear();
		this.spawn();
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
	 * Add or replace one group's SoA element columns. Empty bodies → unwire.
	 * Async: the pack yields every few ms (main belt is >1M rows), so callers
	 * must not rewire the same id concurrently — the point-cloud system
	 * serializes rebuild passes for this reason.
	 *
	 * Never allocates a fresh back while one is in flight: that would let a new
	 * tick dispatch before the old result returns and get paired with the wrong
	 * pendingBasis/pendingParent, misplacing the cloud. Leaving back null defers
	 * dispatch until the in-flight tick lands.
	 */
	async rewireOne(
		id: string,
		bodies: PositionedBody[],
		skip: Set<string>,
		workerHint: number,
		applyFlagFilter: boolean = false,
		pickBase: number = 0
	): Promise<void> {
		if (bodies.length === 0) {
			this.unwireOne(id);
			return;
		}
		const cols = await packBodiesSliced(bodies, skip, applyFlagFilter);
		cols.pickBase = pickBase;
		// Pool may have been destroyed while the pack yielded.
		if (this.workers.length === 0) return;
		this.wireCols(id, cols, workerHint, bodies.length);
	}

	/**
	 * Wire a group whose `OrbitColumns` are already built (columnar minor path —
	 * {@link MinorBucket.buildWorkerGroups} fills SoA directly from the binary,
	 * skipping the `PositionedBody[]` round-trip). Same bookkeeping as {@link rewireOne}, minus the pack.
	 */
	rewireOneCols(id: string, cols: OrbitColumns, workerHint: number): void {
		if (this.workers.length === 0) return;
		if (cols.count === 0) {
			this.unwireOne(id);
			return;
		}
		this.wireCols(id, cols, workerHint, cols.count);
	}

	private wireCols(id: string, cols: OrbitColumns, workerHint: number, capacity: number): void {
		// Read group state fresh — an in-flight tick may have landed meanwhile
		// and swapped front/back.
		const prev = this.groups.get(id);
		const workerIdx = prev?.workerIdx ?? workerHint % this.workers.length;

		let front: Float32Array;
		let back: Float32Array | null;
		let idFront: Uint8Array;
		let idBack: Uint8Array | null;
		if (prev && prev.capacity === capacity) {
			front = prev.front;
			back = prev.back;
			idFront = prev.idFront;
			idBack = prev.idBack;
		} else {
			front = new Float32Array(capacity * 3);
			back = new Float32Array(capacity * 3);
			idFront = new Uint8Array(capacity * 4);
			idBack = new Uint8Array(capacity * 4);
			if (prev) {
				const n = Math.min(prev.front.length, front.length);
				front.set(prev.front.subarray(0, n));
				const idn = Math.min(prev.idFront.length, idFront.length);
				idFront.set(prev.idFront.subarray(0, idn));
			}
		}

		// If a tick is in flight, preserve pending dispatch state so the result
		// pairs with the basis/parent it was actually computed under.
		const inFlight = !!prev && prev.back === null;
		this.groups.set(id, {
			workerIdx,
			capacity,
			front,
			back,
			idFront,
			idBack,
			count: prev?.count ?? capacity,
			pendingBasis: inFlight ? prev!.pendingBasis : null,
			pendingParent: inFlight ? prev!.pendingParent : null,
			pendingJd: inFlight ? prev!.pendingJd : null,
			frontBasis: prev?.frontBasis ?? [0, 0, 0],
			frontParent: prev?.frontParent ?? [0, 0, 0],
			frontJd: prev?.frontJd ?? NaN
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

	/** Per-frame dispatch. Skips groups with no free back-buffer (still on last
	 *  tick; catch up next frame) or absent from `parents` (hidden clouds).
	 *  `requiredFlags` (0 = none) is the NEO/PHA filter for `applyFlagFilter` groups. */
	tick(jd: number, basis: Vec3, parents: Map<string, Vec3>, requiredFlags: number = 0): void {
		const perWorker: {
			id: string;
			parent: [number, number, number];
			out: Float32Array;
			outIds: Uint8Array;
		}[][] = this.workers.map(() => []);

		for (const [id, state] of this.groups) {
			if (!state.back || !state.idBack) continue;
			const parent = parents.get(id);
			if (!parent) continue;
			perWorker[state.workerIdx].push({
				id,
				parent: [parent[0], parent[1], parent[2]],
				out: state.back,
				outIds: state.idBack
			});
			state.back = null;
			state.idBack = null;
			state.pendingBasis = [basis[0], basis[1], basis[2]];
			state.pendingParent = [parent[0], parent[1], parent[2]];
			state.pendingJd = jd;
		}

		for (let i = 0; i < this.workers.length; i++) {
			const groupMsgs = perWorker[i];
			if (groupMsgs.length === 0) continue;
			const transfers: Transferable[] = groupMsgs.flatMap((g) => [
				g.out.buffer as Transferable,
				g.outIds.buffer as Transferable
			]);
			this.workers[i].postMessage(
				{
					type: 'tick',
					jd,
					basis: [basis[0], basis[1], basis[2]],
					requiredFlags,
					groups: groupMsgs
				},
				transfers
			);
		}
	}

	private onMessage(msg: PoolInMsg): void {
		if (msg.type === 'pong') {
			const p = this.pendingPing;
			if (p && ++p.got >= p.need) p.resolve(true);
			return;
		}
		if (msg.type !== 'tickResult') return;
		for (const g of msg.groups) {
			const state = this.groups.get(g.id);
			if (!state) continue;
			const returned = new Float32Array(g.buf);
			const oldFront = state.front;
			state.front = returned;
			state.back = oldFront;
			const returnedIds = new Uint8Array(g.idbuf);
			const oldIdFront = state.idFront;
			state.idFront = returnedIds;
			state.idBack = oldIdFront;
			state.count = g.count;
			const basis = state.pendingBasis ?? state.frontBasis;
			const parent = state.pendingParent ?? state.frontParent;
			const jd = state.pendingJd ?? state.frontJd;
			state.frontBasis = basis;
			state.frontParent = parent;
			state.frontJd = jd;
			state.pendingBasis = null;
			state.pendingParent = null;
			state.pendingJd = null;
			this.onResult?.(g.id, returned, g.count, basis, parent, jd, returnedIds);
		}
	}

	destroy(): void {
		this.pendingPing?.resolve(false);
		for (const w of this.workers) w.terminate();
		this.workers.length = 0;
		this.groups.clear();
	}
}
