/// <reference lib="webworker" />

/*
 * Travel worker: solves one porkchop grid per request and picks the routes to
 * offer from it.
 *
 * A grid is tens of thousands of Lambert solves — fast individually, but enough
 * in aggregate to drop frames if run on the main thread while the user is
 * dragging the map. Requests carry an id so a superseded one can be discarded
 * on arrival rather than cancelled mid-solve; the grids are small and the
 * solves are short, so there is nothing to gain from finer-grained interruption.
 */

import type { TravelBody } from './body';
import { computePorkchop, selectRoutes, type PorkchopOptions, type RouteChoice } from './porkchop';
import type { PorkchopGrid } from './porkchop';

export interface TravelRequest {
	type: 'solve';
	id: number;
	departure: TravelBody;
	target: TravelBody;
	options: PorkchopOptions;
}

export interface TravelResponse {
	type: 'solved';
	id: number;
	grid: PorkchopGrid;
	routes: RouteChoice[];
}

self.onmessage = (ev: MessageEvent<TravelRequest>) => {
	const msg = ev.data;
	if (msg.type !== 'solve') return;

	const grid = computePorkchop(msg.departure, msg.target, msg.options);
	const routes = selectRoutes(grid, msg.departure, msg.target, msg.options);

	const response: TravelResponse = { type: 'solved', id: msg.id, grid, routes };
	(self as unknown as Worker).postMessage(response, [
		grid.departJds.buffer as Transferable,
		grid.tofDays.buffer as Transferable,
		grid.totalDvKms.buffer as Transferable,
		grid.c3Km2S2.buffer as Transferable,
		grid.vInfArrKms.buffer as Transferable
	]);
};

export {}; // ensure this file is treated as a module
