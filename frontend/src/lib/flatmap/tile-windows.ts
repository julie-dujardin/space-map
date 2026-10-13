/**
 * The tile windows of one picture layer of a flat map.
 *
 * A window holds the tile pixels that the frame shows, cut to the frame. The
 * tiles themselves are not claimed: a tile is a megapixel, and a small map
 * shows a fraction of it. For a map that the reader can move, the shared
 * store keeps the decoded tiles that fit its budget, so a pan near the last
 * frame does not decode them again.
 */

import { tileUrl } from '$lib/fetch/data-base';
import type { TilesBlock } from '$lib/scene/types';
import type { DetailCanvas, DetailRaster } from './raster';
import { acquireBitmap, releaseBitmap } from './texture-cache';
import { covers, windowTiles, type WindowSpec } from './tile-plan';

/** Failed fetches in a row before the tile host is given up. */
const MAX_FAILURES = 4;

/** Windows of an earlier frame that stay drawn while the new ones load. */
const MAX_STALE = 2;

/** How a map reads a window: a canvas to draw, or pixels to sample. */
export type WindowKind = 'canvas' | 'pixels';

interface HeldWindow extends WindowSpec {
	tileSize: number;
	/** Month of a monthly map. */
	frame: number | undefined;
	/** The canvas of a window that is drawn. */
	ctx?: CanvasRenderingContext2D;
	/** The pixels of a window that is sampled. */
	data?: Uint8ClampedArray;
	/** Tiles that are not in yet. */
	pending: number;
	/** Part of the last plan. */
	wanted: boolean;
	dropped: boolean;
}

let scratch: CanvasRenderingContext2D | null = null;

/** Copy the part of a tile that is inside a window into its pixels. */
function copyTile(win: HeldWindow, tile: ImageBitmap, dx: number, dy: number): void {
	const x0 = Math.max(dx, 0);
	const y0 = Math.max(dy, 0);
	const width = Math.min(dx + tile.width, win.width) - x0;
	const height = Math.min(dy + tile.height, win.height) - y0;
	if (width <= 0 || height <= 0) return;
	scratch ??= document.createElement('canvas').getContext('2d', { willReadFrequently: true });
	if (!scratch) return;
	if (scratch.canvas.width < tile.width || scratch.canvas.height < tile.height) {
		scratch.canvas.width = tile.width;
		scratch.canvas.height = tile.height;
	}
	scratch.globalCompositeOperation = 'copy';
	scratch.drawImage(tile, x0 - dx, y0 - dy, width, height, 0, 0, width, height);
	const pixels = scratch.getImageData(0, 0, width, height).data;
	const row = width * 4;
	for (let y = 0; y < height; y++) {
		win.data!.set(pixels.subarray(y * row, (y + 1) * row), ((y0 + y) * win.width + x0) * 4);
	}
}

export class LayerTiles {
	private windows: HeldWindow[] = [];
	private kind: WindowKind = 'pixels';
	private failures = 0;
	/** Tiles that the host did not give. They are not asked for again. */
	private readonly failed = new Set<string>();
	/** The tile host cannot serve this pyramid. The whole-body pictures then
	 *  stand alone. */
	dead = false;

	/**
	 * `changed` is called when the windows have new pixels to draw. `moves`
	 * tells whether the reader can move the map: the decoded tiles of a map that
	 * stays in place are not kept for a later frame.
	 */
	constructor(
		readonly block: TilesBlock,
		private readonly changed: () => void,
		private readonly moves: () => boolean
	) {}

	/**
	 * Hold a window for each of `specs`. A window of an earlier plan stays until
	 * the new ones are whole, so the map does not go back to its coarse picture
	 * while tiles load.
	 */
	plan(specs: readonly WindowSpec[], kind: WindowKind, frame: number | undefined): void {
		if (kind !== this.kind) {
			this.clear();
			this.kind = kind;
		}
		for (const win of this.windows) win.wanted = false;
		for (const spec of this.dead ? [] : specs) {
			const held = this.windows.find(
				(win) => win.frame === frame && covers(win, spec, this.block.tile_size)
			);
			if (held) held.wanted = true;
			else this.windows.push(this.open(spec, frame));
		}
		this.prune();
	}

	/** The windows to sample, finest first. */
	rasters(): DetailRaster[] {
		return this.ordered().filter((win): win is HeldWindow & DetailRaster => !!win.data);
	}

	/** The windows to draw, finest first. */
	canvases(): DetailCanvas[] {
		return this.ordered().flatMap((win) => (win.ctx ? [{ ...win, canvas: win.ctx.canvas }] : []));
	}

	clear(): void {
		for (const win of this.windows) this.drop(win);
		this.windows = [];
	}

	/** Free a window. A tile that is still on its way is then not put in. */
	private drop(win: HeldWindow): void {
		win.dropped = true;
		win.data = undefined;
		// A canvas keeps its pixels until it is collected. One of no size has none.
		if (win.ctx) win.ctx.canvas.width = 0;
	}

	/** Finest first. At one level the new window is before the old one. */
	private ordered(): HeldWindow[] {
		return [...this.windows].sort(
			(a, b) => b.level - a.level || Number(b.wanted) - Number(a.wanted)
		);
	}

	private open(spec: WindowSpec, frame: number | undefined): HeldWindow {
		const win: HeldWindow = {
			...spec,
			tileSize: this.block.tile_size,
			frame,
			pending: 0,
			wanted: true,
			dropped: false
		};
		if (this.kind === 'canvas') {
			const canvas = document.createElement('canvas');
			canvas.width = spec.width;
			canvas.height = spec.height;
			win.ctx = canvas.getContext('2d') ?? undefined;
		} else {
			win.data = new Uint8ClampedArray(spec.width * spec.height * 4);
		}
		for (const tile of windowTiles(spec, this.block)) {
			// A patch is built apart from its pyramid, and has its own cache token.
			const pyramid = { id: this.block.id, version: tile.patch?.version ?? this.block.version };
			const url = tileUrl(pyramid, tile.cap, tile.level, tile.x, tile.y, frame);
			if (this.failed.has(url)) continue;
			win.pending++;
			void this.load(win, url, tile.dx, tile.dy);
		}
		return win;
	}

	private async load(win: HeldWindow, url: string, dx: number, dy: number): Promise<void> {
		try {
			const held = await acquireBitmap(url, null);
			if (held) {
				try {
					if (win.ctx && !win.dropped) win.ctx.drawImage(held.bitmap, dx, dy);
					else if (!win.dropped) copyTile(win, held.bitmap, dx, dy);
				} finally {
					releaseBitmap(held.key, this.moves());
				}
			}
			this.failures = 0;
		} catch {
			this.failed.add(url);
			if (++this.failures >= MAX_FAILURES) this.dead = true;
		}
		win.pending--;
		if (this.dead) this.clear();
		else if (win.dropped) return;
		else if (win.pending === 0) this.prune();
		this.changed();
	}

	/** Drop the windows of earlier plans: all of them when the plan is whole,
	 *  and all but the last ones while it loads. */
	private prune(): void {
		const loading = this.windows.some((win) => win.wanted && win.pending > 0);
		const stale = this.windows.filter((win) => !win.wanted);
		const kept = loading ? stale.slice(-MAX_STALE) : [];
		for (const win of stale) if (!kept.includes(win)) this.drop(win);
		this.windows = this.windows.filter((win) => !win.dropped);
	}
}
