import type { PositionedBody } from '$lib/types/objects';
import type { Vec3 } from '$lib/scene/animation/math';
// Inline: a respawn must not refetch a hashed script a redeploy has since removed.
import OrbitWorker from './worker?worker&inline';
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
 * group is skipped on the frame's tick. A dispatch that never comes back
 * (worker threw, or a mobile OS dropped it) would leave the group skipped for
 * good, so tick watches in-flight age and reports a stall (see {@link setStallHandler}).
 */

/** Frame-driven time a dispatch may stay in flight before it counts as lost.
 *  A main-belt solve is tens of ms even on slow phones. */
const STALL_MS = 5000;
/** Most of one tick-to-tick gap that ages an in-flight dispatch: a hidden tab
 *  or a paused clock must not make a reply queued behind the pause look lost. */
const MAX_TICK_GAP_MS = 250;

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
	/** {@link OrbitWorkerPool.activeMs} at dispatch of the in-flight tick. */
	dispatchedAt: number;
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
	private pendingPing: {
		need: number;
		got: number;
		promise: Promise<boolean>;
		resolve: (ok: boolean) => void;
	} | null = null;
	private generation = 0;
	private onStall: (() => void) | null = null;
	/** Time summed over tick-to-tick gaps, each capped at {@link MAX_TICK_GAP_MS}. */
	private activeMs = 0;
	private lastTickAt = NaN;
	private lastStallAt = -Infinity;
	/** A respawned pool that has not answered yet. Its stalls go unreported:
	 *  workers that can't start would otherwise respawn in a loop. */
	private unprovenRespawn = false;

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
			// An uncaught throw drops the tick in flight; the worker stays up and
			// would still answer a ping.
			w.onerror = (ev) => {
				console.warn('[orbit-pool] worker error:', ev.message);
				this.reportStall('a worker threw');
			};
			this.workers.push(w);
		}
	}

	/**
	 * True once every worker answers within `timeoutMs`. A backgrounded tab's
	 * workers can be killed by the mobile OS yet still look alive on the main
	 * thread — a timeout is the only signal they're dead. A concurrent caller
	 * joins the in-flight probe: cancelling it would report a live pool as dead
	 * and trigger a second respawn on top of the first one's rewire.
	 */
	ping(timeoutMs = 800): Promise<boolean> {
		if (this.workers.length === 0) return Promise.resolve(false);
		if (this.pendingPing) return this.pendingPing.promise;
		let resolveOuter!: (ok: boolean) => void;
		const promise = new Promise<boolean>((r) => (resolveOuter = r));
		// Guard by identity so an already-resolved probe no-ops; lets the
		// dangling timer expire without a clearTimeout.
		const state = {
			need: this.workers.length,
			got: 0,
			promise,
			resolve: (ok: boolean) => {
				if (this.pendingPing !== state) return;
				this.pendingPing = null;
				resolveOuter(ok);
			}
		};
		this.pendingPing = state;
		setTimeout(() => state.resolve(false), timeoutMs);
		for (const w of this.workers) w.postMessage({ type: 'ping' });
		return promise;
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
		this.generation++;
		this.unprovenRespawn = true;
		this.lastStallAt = -Infinity;
		this.spawn();
	}

	/** Bumped by every {@link respawn}. A rewire pass that spans a bump wired
	 *  groups into a pool that no longer exists and must redo them. */
	get poolGeneration(): number {
		return this.generation;
	}

	setResultHandler(handler: GroupResultHandler): void {
		this.onResult = handler;
	}

	/**
	 * Called when a dispatch has been in flight past {@link STALL_MS} or a
	 * worker threw. The pool can't recover that group itself — its buffers went
	 * with the lost tick — and a ping may still pass, so the handler should
	 * {@link respawn} and re-wire. Repeats at most once per stall window.
	 */
	setStallHandler(handler: () => void): void {
		this.onStall = handler;
	}

	private reportStall(reason: string): void {
		if (this.unprovenRespawn || this.workers.length === 0) return;
		if (this.activeMs - this.lastStallAt < STALL_MS) return;
		this.lastStallAt = this.activeMs;
		console.warn(`[orbit-pool] ${reason}; recovering`);
		this.onStall?.();
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
			frontJd: prev?.frontJd ?? NaN,
			dispatchedAt: inFlight ? prev!.dispatchedAt : NaN
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
		const now = performance.now();
		if (!Number.isNaN(this.lastTickAt))
			this.activeMs += Math.min(now - this.lastTickAt, MAX_TICK_GAP_MS);
		this.lastTickAt = now;
		let stalled = false;

		const perWorker: {
			id: string;
			parent: [number, number, number];
			out: Float32Array;
			outIds: Uint8Array;
		}[][] = this.workers.map(() => []);

		for (const [id, state] of this.groups) {
			if (!state.back || !state.idBack) {
				if (this.activeMs - state.dispatchedAt > STALL_MS) stalled = true;
				continue;
			}
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
			state.dispatchedAt = this.activeMs;
		}
		if (stalled) this.reportStall('a dispatch never came back');

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
		this.unprovenRespawn = false;
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
