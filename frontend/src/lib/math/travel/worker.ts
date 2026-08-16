/// <reference lib="webworker" />

/*
 * Solves a porkchop grid (tens of thousands of Lambert solves) off the main
 * thread so dragging the map stays smooth, and separately hunts swing-by
 * routes, which sweep a decade of departures and take much longer — kept as
 * its own message so the three direct routes don't wait on it. Requests carry
 * an id so a superseded one is discarded on arrival rather than cancelled
 * mid-solve.
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
