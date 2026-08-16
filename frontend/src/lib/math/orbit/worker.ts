/// <reference lib="webworker" />
import { writePositions, type OrbitColumns } from './soa';

/*
 * Orbit worker: owns a subset of point-cloud groups and each frame solves
 * Kepler/Barker for every owned body, driven by messages from
 * OrbitWorkerPool on the main thread.
 *
 * 'rewireDelta' adds/replaces/removes groups by id without re-packing others.
 * 'tick' asks for fresh positions at a jd + per-group parent + shared basis;
 * main sends one free Float32Array per group (transferred), worker writes
 * and transfers it back with a count.
 *
 * Number arrays are Float64 internally for precision; only the output
 * position buffer is Float32 (matches the Three.js BufferAttribute).
 */

const groups = new Map<string, OrbitColumns>();

type RewireDeltaMsg = {
	type: 'rewireDelta';
	set: { id: string; cols: OrbitColumns }[];
	remove?: string[];
};

type TickMsg = {
	type: 'tick';
	jd: number;
	basis: [number, number, number];
	/** Per-tick NEO/PHA mask; hides points whose flags lack every set bit. */
	requiredFlags?: number;
	groups: {
		id: string;
		parent: [number, number, number];
		/** Pre-allocated Float32Array the worker writes into (length = capacity*3). */
		out: Float32Array;
		/** Pre-allocated pick-id bytes buffer (length = capacity*4), written in
		 *  lockstep with `out` and transferred back for GPU picking. */
		outIds: Uint8Array;
	}[];
};

/** Liveness probe answered with `pong`; lets the pool spot OS-killed workers. */
type PingMsg = { type: 'ping' };

type InMsg = RewireDeltaMsg | TickMsg | PingMsg;

self.onmessage = (ev: MessageEvent<InMsg>) => {
	const msg = ev.data;
	if (msg.type === 'ping') {
		(self as unknown as Worker).postMessage({ type: 'pong' });
		return;
	}
	if (msg.type === 'rewireDelta') {
		if (msg.remove) for (const id of msg.remove) groups.delete(id);
		for (const g of msg.set) groups.set(g.id, g.cols);
		return;
	}
	if (msg.type === 'tick') {
		const out: { id: string; count: number; buf: ArrayBufferLike; idbuf: ArrayBufferLike }[] = [];
		const transfers: Transferable[] = [];
		const [bx, by, bz] = msg.basis;
		for (const g of msg.groups) {
			const cols = groups.get(g.id);
			if (!cols) {
				// Return both buffers back unmodified so main can reuse them.
				out.push({ id: g.id, count: 0, buf: g.out.buffer, idbuf: g.outIds.buffer });
				transfers.push(g.out.buffer as Transferable, g.outIds.buffer as Transferable);
				continue;
			}
			const count = writePositions(
				cols,
				msg.jd,
				g.parent[0],
				g.parent[1],
				g.parent[2],
				bx,
				by,
				bz,
				g.out,
				g.outIds,
				msg.requiredFlags ?? 0
			);
			out.push({ id: g.id, count, buf: g.out.buffer, idbuf: g.outIds.buffer });
			transfers.push(g.out.buffer as Transferable, g.outIds.buffer as Transferable);
		}
		(self as unknown as Worker).postMessage({ type: 'tickResult', groups: out }, transfers);
		return;
	}
};

export {}; // ensure this file is treated as a module
