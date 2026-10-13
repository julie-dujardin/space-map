/// <reference lib="webworker" />

/*
 * Height tiles off the main thread.
 *
 * A tile is a megapixel to read out of a canvas, and a window of the relief
 * chain takes sixteen: this worker fetches and decodes them, and gives the
 * bytes back. It also builds the terrain grid: it keeps the few tiles that
 * the grid's vertices read, so those megabytes never reach the main thread.
 */

import { tilePath } from '$lib/fetch/tile-path';
import { type GridAxis, buildGridArrays } from '$lib/scene/lod/terrain-grid';
import { CHART_FOLDER } from '$lib/scene/lod/tile-window';
import { gridHeights, gridTiles, tileOfKey } from './grid-heights';
import { heightValues, packHeightBytes } from './heights';

export interface TileRequest {
	type: 'tile';
	id: number;
	url: string;
}

export interface GridRequest {
	type: 'grid';
	id: number;
	/** Folder of the pyramid, as a full URL, and its cache token. */
	root: string;
	version: string;
	tileSize: number;
	/** A vertex is `biasKm + scaleKm · value / 65535` above the sphere. */
	scaleKm: number;
	biasKm: number;
	/** Radius of the sphere in the mesh's units, and those units per km. */
	radius: number;
	unitsPerKm: number;
	rows: GridAxis;
	columns: GridAxis;
}

export interface AbortRequest {
	type: 'abort';
	id: number;
}

export type ReliefRequest = TileRequest | GridRequest | AbortRequest;

export interface TileResponse {
	type: 'tile';
	id: number;
	size: number;
	/** Two bytes per pixel, south row first. */
	bytes: Uint8Array;
}

export interface GridResponse {
	type: 'grid';
	id: number;
	positions: Float32Array;
	normals: Float32Array;
	uvs: Float32Array;
	indices: Uint32Array;
	/** Height of each vertex above the sphere, row by row. */
	riseKm: Float32Array;
}

export interface FailedResponse {
	type: 'failed';
	id: number;
}

export type ReliefResponse = TileResponse | GridResponse | FailedResponse;

/** Tile fetches the grid has in flight at once. */
const GRID_FETCHES = 6;

const post = self as unknown as Worker;
const inflight = new Map<number, AbortController>();

let canvas: OffscreenCanvas | undefined;

/** The pixels of the tile at `url`, north row first. */
async function decodeTile(
	url: string,
	signal: AbortSignal
): Promise<{ rgba: Uint8ClampedArray; size: number }> {
	const response = await fetch(url, { signal });
	if (!response.ok) throw new Error(`tile ${response.status}`);
	// The bytes are heights: nothing may convert them on the way.
	const bitmap = await createImageBitmap(await response.blob(), {
		premultiplyAlpha: 'none',
		colorSpaceConversion: 'none'
	});
	const size = bitmap.width;
	if (canvas?.width !== size) canvas = new OffscreenCanvas(size, size);
	const context = canvas.getContext('2d', { willReadFrequently: true });
	if (!context) throw new Error('no 2d canvas in this worker');
	context.globalCompositeOperation = 'copy';
	context.drawImage(bitmap, 0, 0);
	bitmap.close();
	return { rgba: context.getImageData(0, 0, size, size).data, size };
}

async function sendTile(request: TileRequest, signal: AbortSignal): Promise<void> {
	const { rgba, size } = await decodeTile(request.url, signal);
	const bytes = packHeightBytes(rgba, size);
	post.postMessage({ type: 'tile', id: request.id, size, bytes } satisfies TileResponse, [
		bytes.buffer
	]);
}

/** The tiles of the last grid, by key, for the pyramid at `gridRoot`. The
 *  next grid is mostly on the same ones. */
const gridCache = new Map<number, Uint16Array>();
let gridRoot = '';

async function sendGrid(request: GridRequest, signal: AbortSignal): Promise<void> {
	const { rows, columns, tileSize } = request;
	const root = `${request.root}?${request.version}`;
	if (root !== gridRoot) gridCache.clear();
	gridRoot = root;

	const needed = gridTiles(rows, columns, tileSize);
	const queue = [...needed].filter((key) => !gridCache.has(key));
	const fetchNext = async (): Promise<void> => {
		for (let key = queue.pop(); key !== undefined; key = queue.pop()) {
			const { chart, level, x, y } = tileOfKey(key);
			const url = `${request.root}${tilePath(CHART_FOLDER[chart], level, x, y)}?v=${request.version}`;
			try {
				const { rgba, size } = await decodeTile(url, signal);
				gridCache.set(key, heightValues(rgba, size));
			} catch {
				// Its vertices take the level below.
				if (signal.aborted) return;
			}
		}
	};
	await Promise.all(Array.from({ length: GRID_FETCHES }, fetchNext));
	signal.throwIfAborted();

	const riseKm = gridHeights(
		rows,
		columns,
		(key) => gridCache.get(key),
		tileSize,
		request.scaleKm,
		request.biasKm
	);
	for (const key of [...gridCache.keys()]) if (!needed.has(key)) gridCache.delete(key);
	if (!riseKm) throw new Error('no height tiles for the grid');

	const grid = buildGridArrays(request.radius, rows.at, columns.at, riseKm, request.unitsPerKm);
	// The index array is a view of a longer buffer.
	const indices = grid.indices.slice();
	post.postMessage(
		{ type: 'grid', id: request.id, ...grid, indices, riseKm } satisfies GridResponse,
		[grid.positions.buffer, grid.normals.buffer, grid.uvs.buffer, indices.buffer, riseKm.buffer]
	);
}

async function answer(request: TileRequest | GridRequest): Promise<void> {
	const abort = new AbortController();
	inflight.set(request.id, abort);
	try {
		if (request.type === 'tile') await sendTile(request, abort.signal);
		else await sendGrid(request, abort.signal);
	} catch {
		post.postMessage({ type: 'failed', id: request.id } satisfies FailedResponse);
	} finally {
		inflight.delete(request.id);
	}
}

self.onmessage = (ev: MessageEvent<ReliefRequest>) => {
	const msg = ev.data;
	if (msg.type === 'abort') inflight.get(msg.id)?.abort();
	else void answer(msg);
};
