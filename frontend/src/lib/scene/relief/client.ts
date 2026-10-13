/**
 * Main-thread handle on the relief worker, which is started by the first
 * request: a session that never comes close to a body with height tiles never
 * pays for it.
 */

import type {
	GridRequest,
	GridResponse,
	ReliefRequest,
	ReliefResponse,
	TileResponse
} from './worker';
import ReliefWorker from './worker?worker';

interface Pending {
	resolve: (answer: ReliefResponse) => void;
	reject: (reason: Error) => void;
}

let worker: Worker | null = null;
let nextId = 1;
const pending = new Map<number, Pending>();

/** A worker that dies takes its answers with it: fail them, so their callers
 *  fall back, and let the next request start another. */
function drop(reason: string): void {
	worker?.terminate();
	worker = null;
	const lost = [...pending.values()];
	pending.clear();
	for (const { reject } of lost) reject(new Error(reason));
}

function ensureWorker(): Worker {
	if (worker) return worker;
	worker = new ReliefWorker();
	worker.onmessage = (ev: MessageEvent<ReliefResponse>) => {
		const msg = ev.data;
		const request = pending.get(msg.id);
		pending.delete(msg.id);
		if (!request) return;
		if (msg.type === 'failed') request.reject(new Error('relief worker could not answer'));
		else request.resolve(msg);
	};
	worker.onerror = (ev) => drop(`relief worker error: ${ev.message || 'unknown'}`);
	worker.onmessageerror = () => drop('relief worker sent a message that could not be read');
	return worker;
}

/** Send what `build` makes of a fresh id. Rejects when the worker cannot
 *  answer, or on `signal`. */
function ask(build: (id: number) => ReliefRequest, signal: AbortSignal): Promise<ReliefResponse> {
	return new Promise((resolve, reject) => {
		if (typeof Worker === 'undefined') {
			reject(new Error('no workers here'));
			return;
		}
		const id = nextId++;
		pending.set(id, { resolve, reject });
		signal.addEventListener(
			'abort',
			() => {
				if (!pending.delete(id)) return;
				ensureWorker().postMessage({ type: 'abort', id } satisfies ReliefRequest);
				reject(new DOMException('aborted', 'AbortError'));
			},
			{ once: true }
		);
		ensureWorker().postMessage(build(id));
	});
}

/** A worker made from a blob has no page to resolve a relative URL against. */
function absolute(url: string): string {
	return new URL(url, location.href).href;
}

/** The height tile at `url`, decoded. */
export function loadHeightTile(url: string, signal: AbortSignal): Promise<TileResponse> {
	return ask((id) => ({ type: 'tile', id, url: absolute(url) }), signal) as Promise<TileResponse>;
}

/** A terrain grid with its heights from the pyramid at `spec.root`. */
export function buildTerrainGrid(
	spec: Omit<GridRequest, 'type' | 'id'>,
	signal: AbortSignal
): Promise<GridResponse> {
	return ask(
		(id) => ({ ...spec, type: 'grid', id, root: absolute(spec.root) }),
		signal
	) as Promise<GridResponse>;
}
