/// <reference lib="webworker" />

/*
 * Travel worker: solves one porkchop grid per request and picks the routes to
 * offer from it, and — on a separate request — hunts for a swing-by route.
 *
 * A grid is tens of thousands of Lambert solves — fast individually, but enough
 * in aggregate to drop frames if run on the main thread while the user is
 * dragging the map. Requests carry an id so a superseded one can be discarded
 * on arrival rather than cancelled mid-solve; the grids are small and the
 * solves are short, so there is nothing to gain from finer-grained interruption.
 *
 * The swing-by hunt is the same argument an order of magnitude louder: it sweeps
 * a decade of departures against two cruise lengths for every candidate body.
 * It is a separate message rather than part of the solve because it answers a
 * second or so later, and the three direct routes should not wait for it.
 */

import type { TravelBody } from './body';
import { findAssistRoute, type AssistOptions } from './assist';
import { computePorkchop, selectRoutes, type PorkchopOptions, type RouteChoice } from './porkchop';
import type { PorkchopGrid } from './porkchop';
import type { Route } from './route';

export interface SolveRequest {
	type: 'solve';
	id: number;
	departure: TravelBody;
	target: TravelBody;
	options: PorkchopOptions;
}

export interface AssistRequest {
	type: 'assist';
	id: number;
	departure: TravelBody;
	target: TravelBody;
	vias: TravelBody[];
	options: AssistOptions;
}

export type TravelRequest = SolveRequest | AssistRequest;

export interface SolveResponse {
	type: 'solved';
	id: number;
	grid: PorkchopGrid;
	routes: RouteChoice[];
}

export interface AssistResponse {
	type: 'assisted';
	id: number;
	route: Route | null;
}

export type TravelResponse = SolveResponse | AssistResponse;

self.onmessage = (ev: MessageEvent<TravelRequest>) => {
	const msg = ev.data;
	const post = self as unknown as Worker;

	if (msg.type === 'assist') {
		const route = findAssistRoute(msg.departure, msg.target, msg.vias, msg.options);
		post.postMessage({ type: 'assisted', id: msg.id, route } satisfies AssistResponse);
		return;
	}
	if (msg.type !== 'solve') return;

	const grid = computePorkchop(msg.departure, msg.target, msg.options);
	const routes = selectRoutes(grid, msg.departure, msg.target, msg.options);

	const response: SolveResponse = { type: 'solved', id: msg.id, grid, routes };
	post.postMessage(response, [
		grid.departJds.buffer as Transferable,
		grid.tofDays.buffer as Transferable,
		grid.totalDvKms.buffer as Transferable,
		grid.c3Km2S2.buffer as Transferable,
		grid.vInfArrKms.buffer as Transferable
	]);
};

export {}; // ensure this file is treated as a module
